"""Contract tests for metadata-driven raw dataset export containers."""

import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.site import Site
from app.models.edc.study import Study, StudyStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.shared.export import Export, ExportStatus
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
    UserStatus,
)
from app.schemas.designer.raw_data_variable_setting import RawDatasetVariableResponse
from app.services.edc.raw_dataset_export_service import (
    RawDatasetPackage,
    RawDatasetTable,
    raw_dataset_export_service,
)
from app.workers.export_worker import (
    serialize_csv_package,
    serialize_excel_package,
    serialize_json_package,
    serialize_odm_dataset_package,
    serialize_sas_xpt_package,
)


def _package() -> RawDatasetPackage:
    columns = [
        RawDatasetVariableResponse(
            name="PROTOCOL", data_type="string", label="Protocol", source="fixed"
        ),
        RawDatasetVariableResponse(name="AGE", data_type="integer", label="Age", source="field"),
        RawDatasetVariableResponse(
            name="AGE_NUM",
            data_type="decimal",
            label="Age (numeric)",
            source="numeric_companion",
        ),
    ]
    return RawDatasetPackage(
        study_id="study-1",
        generated_at="2026-10-15T12:00:00Z",
        datasets=[
            RawDatasetTable(
                name="DM",
                columns=columns,
                rows=[{"PROTOCOL": "P-001", "AGE": "45", "AGE_NUM": "45"}],
                subject_keys=["subject-1"],
                design_version_ids=["version-1", "version-2"],
                form_definition_ids=["form-1", "form-2"],
            )
        ],
    )


def test_csv_package_contains_dataset_and_manifest() -> None:
    with zipfile.ZipFile(BytesIO(serialize_csv_package(_package()))) as archive:
        assert set(archive.namelist()) == {"manifest.json", "DM.csv"}
        rows = list(csv.DictReader(io.StringIO(archive.read("DM.csv").decode())))
        assert rows == [{"PROTOCOL": "P-001", "AGE": "45", "AGE_NUM": "45"}]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["datasets"][0]["design_version_ids"] == [
            "version-1",
            "version-2",
        ]


def test_json_package_is_keyed_by_dataset() -> None:
    payload = json.loads(serialize_json_package(_package()))
    assert payload["DM"] == [{"PROTOCOL": "P-001", "AGE": "45", "AGE_NUM": "45"}]
    assert payload["_manifest"]["dataset_count"] == 1


def test_excel_package_has_dataset_and_manifest_sheets() -> None:
    with zipfile.ZipFile(BytesIO(serialize_excel_package(_package()))) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode()
        assert 'name="DM"' in workbook_xml
        assert 'name="Manifest"' in workbook_xml
        assert "AGE_NUM" in workbook.read("xl/worksheets/sheet1.xml").decode()


def test_xpt_package_contains_one_transport_member_per_dataset() -> None:
    with zipfile.ZipFile(BytesIO(serialize_sas_xpt_package(_package()))) as archive:
        assert "DM.xpt" in archive.namelist()
        assert archive.read("DM.xpt").startswith(
            b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"
        )
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["datasets"][0]["xpt_variable_names"]["AGE_NUM"] == "AGE_NUM"


def test_odm_package_uses_dataset_item_group_and_variables() -> None:
    root = ET.fromstring(serialize_odm_dataset_package(_package()))
    groups = [
        element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "ItemGroupDef"
    ]
    assert groups[0].attrib["Name"] == "DM"
    values = {
        element.attrib["ItemOID"]: element.attrib["Value"]
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "ItemData"
    }
    assert any(key.endswith("AGE_NUM") and value == "45" for key, value in values.items())


@pytest.mark.asyncio
async def test_builder_merges_versioned_schemas_and_populates_generated_variables() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            actor = User(
                email="exporter@example.com",
                first_name="Export",
                last_name="User",
                status=UserStatus.active,
            )
            permission = Permission(code="data.export", description="Export data")
            role = Role(name=f"Exporter-{uuid4()}", scope_level=ScopeLevel.study)
            session.add_all([actor, permission, role])
            await session.flush()
            session.add(RolePermission(role_id=role.id, permission_id=permission.id))

            study = Study(
                study_code="RAW-001",
                protocol_number="P-001",
                title="Raw export",
                status=StudyStatus.active,
                created_by=actor.id,
            )
            session.add(study)
            await session.flush()
            session.add(
                UserRole(user_id=actor.id, role_id=role.id, study_id=study.id, site_id=None)
            )
            site = Site(
                study_id=study.id,
                site_number="101",
                name="Site 101",
            )
            session.add(site)
            await session.flush()

            version_1 = StudyVersion(
                study_id=study.id,
                version_number="1.0",
                status=StudyVersionStatus.published,
            )
            version_2 = StudyVersion(
                study_id=study.id,
                version_number="2.0",
                status=StudyVersionStatus.published,
            )
            session.add_all([version_1, version_2])
            await session.flush()

            form_1 = FormDefinition(
                study_version_id=version_1.id,
                name="Demographics",
                form_code="DM",
                domain="DM",
                display_order=1,
            )
            form_2 = FormDefinition(
                study_version_id=version_2.id,
                name="Demographics amended",
                form_code="DM",
                domain="DM",
                display_order=1,
            )
            session.add_all([form_1, form_2])
            await session.flush()
            section_1 = FormSection(
                form_definition_id=form_1.id,
                name="Main",
                label="Main",
                display_order=1,
            )
            section_2 = FormSection(
                form_definition_id=form_2.id,
                name="Main",
                label="Main",
                display_order=1,
            )
            session.add_all([section_1, section_2])
            await session.flush()
            age_v1 = FieldDefinition(
                form_section_id=section_1.id,
                label="Age",
                variable_name="AGE",
                control_type="integer",
                data_type="integer",
                is_required=False,
                display_order=1,
            )
            age_v2 = FieldDefinition(
                form_section_id=section_2.id,
                label="Age text",
                variable_name="AGE",
                control_type="text",
                data_type="string",
                is_required=False,
                display_order=1,
            )
            codelist = Codelist(
                study_version_id=version_2.id,
                name="Sex",
                code="SEX",
            )
            session.add_all([age_v1, age_v2, codelist])
            await session.flush()
            session.add_all(
                [
                    CodelistItem(
                        codelist_id=codelist.id,
                        code="F",
                        label="Female",
                        display_order=1,
                    ),
                    RawDataVariableSetting(
                        design_version_id=version_1.id,
                        field_definition_id=age_v1.id,
                        name="AGE",
                        data_type="integer",
                        suffix="STANDARD",
                        attributes={"generation_kind": "numeric"},
                    ),
                ]
            )
            sex_v2 = FieldDefinition(
                form_section_id=section_2.id,
                label="Sex",
                variable_name="SEX",
                control_type="radio",
                data_type="string",
                codelist_id=codelist.id,
                is_required=False,
                display_order=2,
            )
            session.add(sex_v2)
            await session.flush()

            subject = Subject(
                study_id=study.id,
                site_id=site.id,
                study_version_id=version_1.id,
                subject_number="001",
                status=SubjectStatus.enrolled,
                created_by=actor.id,
            )
            session.add(subject)
            await session.flush()
            form_instance = FormInstance(
                subject_id=subject.id,
                form_definition_id=form_1.id,
                design_version_id=version_1.id,
                data_entry_status="Submitted",
                status="Submitted",
                submitted_by=actor.id,
                submitted_at=datetime.now(UTC),
            )
            session.add(form_instance)
            await session.flush()
            session.add(
                FieldValue(
                    form_instance_id=form_instance.id,
                    field_definition_id=age_v1.id,
                    design_version_id=version_1.id,
                    value="45",
                    updated_by=actor.id,
                )
            )
            in_progress_form = FormInstance(
                subject_id=subject.id,
                form_definition_id=form_1.id,
                design_version_id=version_1.id,
                data_entry_status="In Progress",
                status="In Progress",
            )
            session.add(in_progress_form)
            await session.flush()
            session.add(
                FieldValue(
                    form_instance_id=in_progress_form.id,
                    field_definition_id=age_v1.id,
                    design_version_id=version_1.id,
                    value="99",
                    updated_by=actor.id,
                )
            )
            await session.flush()

            export = Export(
                study_id=study.id,
                export_type="csv",
                status=ExportStatus.running,
                requested_by=actor.id,
                filters={},
            )
            package = await raw_dataset_export_service.build_package(session, export)

            assert [table.name for table in package.datasets] == ["DM"]
            table = package.datasets[0]
            assert len(table.rows) == 1
            names = [column.name for column in table.columns]
            assert names[:13] == [
                "PROTOCOL",
                "SITE",
                "SUBJID",
                "SUBJINIT",
                "VISIT",
                "FORM",
                "PROCEDUR",
                "VISITINS",
                "FORMINS",
                "GROUPINS",
                "LRMODDTS",
                "ERMODDDTS",
                "LRMODBY",
            ]
            assert {"AGE", "AGE_STANDARD", "SEX", "SEX_LABEL"}.issubset(names)
            assert table.rows[0]["PROTOCOL"] == "P-001"
            assert table.rows[0]["SITE"] == "101"
            assert table.rows[0]["SUBJID"] == "101001"
            assert table.rows[0]["AGE"] == "45"
            assert table.rows[0]["AGE_STANDARD"] == "45"
            assert table.rows[0]["SEX"] == ""
            assert table.schema_conflicts == [
                {
                    "variable": "AGE",
                    "existing_type": "integer",
                    "additional_type": "string",
                    "design_version_id": str(version_2.id),
                }
            ]
    finally:
        await engine.dispose()
