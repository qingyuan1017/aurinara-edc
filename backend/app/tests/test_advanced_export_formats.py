"""Focused tests for Phase 3 advanced export serializers."""

from __future__ import annotations

import json
import uuid
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree as ET

import pytest

from app.models.export import Export, ExportStatus, ExportType
from app.workers.export_worker import (
    ODM_NS,
    serialize_excel,
    serialize_json,
    serialize_odm_xml,
    serialize_sas_xpt,
)

ROWS = [
    {
        "subject_number": "SUBJ-001",
        "site_number": "SITE-01",
        "visit_name": "Visit 1",
        "form_name": "Demographics",
        "field_variable_name": "AGE",
        "value": "45",
    },
    {
        "subject_number": "SUBJ-002",
        "site_number": "SITE-02",
        "visit_name": "Visit 2",
        "form_name": "Vitals",
        "field_variable_name": "WEIGHT",
        "value": "72.5",
    },
]


def test_json_export_round_trips_canonical_rows() -> None:
    """JSON preserves every canonical row and value without coercion."""
    assert json.loads(serialize_json(ROWS)) == ROWS


def test_excel_export_is_a_readable_xlsx_workbook() -> None:
    """Excel output is a valid OOXML package with the expected worksheet data."""
    workbook = serialize_excel(ROWS)
    with zipfile.ZipFile(BytesIO(workbook)) as archive:
        assert {
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/worksheets/sheet1.xml",
        }.issubset(archive.namelist())
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = [node.text or "" for node in sheet.findall(".//main:is/main:t", namespace)]
    assert values[:6] == [
        "subject_number",
        "site_number",
        "visit_name",
        "form_name",
        "field_variable_name",
        "value",
    ]
    assert "72.5" in values


def test_sas_xpt_export_has_transport_headers_and_data() -> None:
    """SAS output contains XPORT descriptor/observation sections and values."""
    xpt = serialize_sas_xpt(ROWS)
    assert xpt.startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!")
    assert b"NAMESTR HEADER RECORD!!!!!!!" in xpt
    assert b"OBS     HEADER RECORD!!!!!!!" in xpt
    assert b"SUBJ-001" in xpt
    assert b"72.5" in xpt
    assert len(xpt) % 80 == 0


def test_odm_export_contains_metadata_and_subject_data() -> None:
    """ODM output contains metadata definitions and linked clinical values."""
    odm = ET.fromstring(serialize_odm_xml(ROWS))
    assert odm.attrib["ODMVersion"] == "1.3.2"
    ns = {"odm": ODM_NS}
    assert odm.find(".//odm:ItemGroupDef", ns) is not None
    assert odm.find(".//odm:ItemDef[@Name='AGE']", ns) is not None
    subject = odm.find(".//odm:SubjectData[@SubjectKey='SUBJ-002']", ns)
    assert subject is not None
    item = subject.find(".//odm:ItemData[@Value='72.5']", ns)
    assert item is not None


@pytest.mark.asyncio
async def test_advanced_export_dispatches_to_advanced_worker() -> None:
    """The dispatcher routes each Phase 3 format away from the CSV worker."""
    from app.workers.export_worker import run_advanced_export, run_export

    session = AsyncMock()
    for export_type in (
        ExportType.excel,
        ExportType.json,
        ExportType.sas_xpt,
        ExportType.odm_xml,
    ):
        export = Export(
            id=uuid.uuid4(),
            study_id=uuid.uuid4(),
            export_type=export_type,
            status=ExportStatus.queued,
            requested_by=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )
        with patch(
            "app.workers.export_worker.run_advanced_export",
            new_callable=AsyncMock,
        ) as advanced:
            await run_export(session, export)
            advanced.assert_awaited_once_with(session, export)

    assert run_advanced_export is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("export_type", "extension"),
    [
        (ExportType.excel, "xlsx"),
        (ExportType.json, "json"),
        (ExportType.sas_xpt, "xpt"),
        (ExportType.odm_xml, "xml"),
    ],
)
async def test_advanced_worker_generates_and_completes_each_format(
    tmp_path, export_type, extension
) -> None:
    """The worker applies the shared query path and stores every advanced format."""
    from unittest.mock import MagicMock

    from app.models.form_data import FieldValue, FormInstance
    from app.models.form_metadata import FieldDefinition
    from app.models.site import Site
    from app.models.subject import Subject
    from app.models.visit import VisitInstance
    from app.workers.export_worker import run_advanced_export

    site = MagicMock(spec=Site, site_number="SITE-01")
    subject = MagicMock(spec=Subject, subject_number="SUBJ-001", site=site)
    visit = MagicMock(spec=VisitInstance, name="Visit 1")
    form = MagicMock(name="Demographics")
    form_instance = MagicMock(
        spec=FormInstance, subject=subject, visit_instance=visit, form_definition=form
    )
    field = MagicMock(spec=FieldDefinition, variable_name="AGE")
    field_value = MagicMock(
        spec=FieldValue, form_instance=form_instance, field_definition=field, value="45"
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = [field_value]
    session = AsyncMock()
    session.execute.return_value = result
    export = Export(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        export_type=export_type,
        status=ExportStatus.queued,
        requested_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    with (
        patch("app.workers.export_worker.export_service.start_export", new_callable=AsyncMock),
        patch(
            "app.workers.export_worker.export_service.complete_export", new_callable=AsyncMock
        ) as complete,
        patch("app.workers.export_worker.audit_service.record", new_callable=AsyncMock),
        patch(
            "app.workers.export_worker.notification_service.on_export_completed",
            new_callable=AsyncMock,
        ),
        patch("app.workers.export_worker._get_export_dir", return_value=tmp_path),
    ):
        await run_advanced_export(session, export)

    file_path = tmp_path / f"export_{export.id}_{export.study_id}.{extension}"
    assert file_path.exists()
    assert file_path.stat().st_size > 0
    assert complete.await_args.kwargs["file_path"] == str(file_path)
