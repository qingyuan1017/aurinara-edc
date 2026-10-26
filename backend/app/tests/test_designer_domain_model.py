"""Focused tests for the Designer domain-model refactor.

Covers the new/changed Designer behaviors introduced when cycles folded into
visits and the arm/visit mapping, raw-data label/suffix, CRF blinding, and
form/visit dependency capabilities were added:

  - visit_definition_service: cycle visit + repeat/cycle metadata; reject repeat
    fields on a non-cycle visit; reject inverted repeat bounds.
  - arm_service: attach member visits; reject missing / cross-version visit ids;
    dedupe duplicates; list arms with member ids.
  - crf_access_service: blinded / unblind_role; reject unblind_role without
    blinded.
  - raw_data_variable_service: persist label/suffix; strip-empty to None.
  - form_dependency_service / visit_dependency_service: happy path, self-guard,
    duplicate guard, cross-version guard.

Each example runs against a fresh in-memory SQLite database (mirroring
``test_property_designer_round_trip.py``), so the assertions reflect what landed
in the database through the real service contracts.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.subject_phase_definition import SubjectPhaseType
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.schemas.designer.form_metadata import (
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FormDefinitionCreate,
    FormSectionCreate,
)
from app.schemas.designer.visit import VisitDefinitionCreate, VisitDefinitionUpdate
from app.services.designer.arm_service import ArmService
from app.services.designer.coding_setting_service import CodingSettingService
from app.services.designer.crf_access_service import CrfAccessService
from app.services.designer.design_clone_service import DesignCloneService
from app.services.designer.form_dependency_service import FormDependencyService
from app.services.designer.form_metadata_service import FormMetadataService
from app.services.designer.raw_data_variable_service import RawDataVariableService
from app.services.designer.schedule_of_assessment_service import (
    ScheduleEntryInput,
    ScheduleOfAssessmentService,
)
from app.services.designer.subject_phase_service import SubjectPhaseService
from app.services.designer.visit_definition_service import VisitDefinitionService
from app.services.designer.visit_dependency_service import VisitDependencyService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _make_version(session: AsyncSession) -> StudyVersion:
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Domain Model Study",
        status=StudyStatus.draft,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    session.add(version)
    await session.flush()
    return version


async def _make_visit(
    session: AsyncSession,
    version_id: uuid.UUID,
    visit_number: int,
    *,
    visit_type: str = "scheduled",
    definition_kind: str = "visit",
) -> VisitDefinition:
    visit = VisitDefinition(
        study_version_id=version_id,
        name=f"Visit {visit_number}",
        visit_number=visit_number,
        visit_type=visit_type,
        definition_kind=definition_kind,
        display_order=visit_number,
        is_required=True,
    )
    session.add(visit)
    await session.flush()
    return visit


# ---------------------------------------------------------------------------
# visit_definition_service — cycle visit metadata
# ---------------------------------------------------------------------------


async def test_cycle_visit_persists_cycle_metadata():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            cycle = await VisitDefinitionService().define_visit(
                session,
                version=version,
                data=VisitDefinitionCreate(
                    name="Treatment Cycle",
                    visit_number=1,
                    visit_type="cycle",
                    display_order=1,
                    repeat_min=1,
                    repeat_max=6,
                    cycle_length=28,
                ),
                actor_id=uuid.uuid4(),
            )
            assert cycle.visit_type == "cycle"
            assert cycle.repeat_min == 1
            assert cycle.repeat_max == 6
            assert cycle.cycle_length == 28
    finally:
        await engine.dispose()


async def test_repeat_fields_rejected_on_non_cycle_visit():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await VisitDefinitionService().define_visit(
                    session,
                    version=version,
                    data=VisitDefinitionCreate(
                        name="Plain",
                        visit_number=1,
                        visit_type="scheduled",
                        display_order=1,
                        repeat_min=1,
                    ),
                    actor_id=uuid.uuid4(),
                )
            assert exc.value.details["field"] == "visit_type"
    finally:
        await engine.dispose()


async def test_inverted_repeat_bounds_rejected():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await VisitDefinitionService().define_visit(
                    session,
                    version=version,
                    data=VisitDefinitionCreate(
                        name="Cycle",
                        visit_number=1,
                        visit_type="cycle",
                        display_order=1,
                        repeat_min=5,
                        repeat_max=2,
                    ),
                    actor_id=uuid.uuid4(),
                )
            assert exc.value.details["field"] == "repeat_min"
    finally:
        await engine.dispose()


async def test_extended_form_section_and_item_metadata_round_trip():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            service = FormMetadataService()
            actor_id = uuid.uuid4()
            form = await service.create_form(
                session,
                version,
                FormDefinitionCreate(
                    name="Adverse Events",
                    form_code="AE",
                    display_order=1,
                    form_type="header_details",
                    access_type="general_blind",
                    domain="AE",
                    label="Adverse Events",
                    header_name="Event header",
                    detail_name="Event records",
                    detail_type="grid",
                    show_variable_name=True,
                    show_crf_id=True,
                    show_odm_id=True,
                ),
                actor_id,
            )
            section = await service.create_section(
                session,
                version,
                form,
                FormSectionCreate(
                    name="Event details",
                    label="Event details",
                    display_order=1,
                    output_to_dataset=True,
                    help_text="Capture one event per record.",
                    access_type="restricted_edit",
                ),
                actor_id,
            )
            item = await service.create_field(
                session,
                version,
                section,
                FieldDefinitionCreate(
                    label="Severity",
                    question="What was the worst severity?",
                    caption="Worst observed grade",
                    text_align="left",
                    variable_name="AESEV",
                    record_id="AE_RECORD",
                    crf_id="AE_SEV",
                    odm_id="IT.AE.AESEV",
                    control_type="listbox",
                    data_type="string",
                    max_length=20,
                    help_text="Choose one value.",
                    display_order=1,
                ),
                actor_id,
            )

            assert form.form_type == "header_details"
            assert form.access_type == "general_blind"
            assert form.domain == "AE"
            assert form.label == "Adverse Events"
            assert form.header_name == "Event header"
            assert form.detail_type == "grid"
            assert form.show_variable_name is True
            assert section.output_to_dataset is True
            assert section.access_type == "restricted_edit"
            assert item.question == "What was the worst severity?"
            assert item.caption == "Worst observed grade"
            assert item.record_id == "AE_RECORD"
            assert item.crf_id == "AE_SEV"
            assert item.odm_id == "IT.AE.AESEV"
            assert item.control_type == "listbox"

            # Mutation routes traverse field -> section -> form -> version.
            # Expire the identity map so this assertion catches accidental
            # async lazy loads rather than reusing the objects created above.
            version_id = version.id
            item_id = item.id
            session.expire_all()
            loaded_item = await service.get_field(session, item_id)
            assert loaded_item.form_section.form_definition.study_version.id == version_id

            updated_item = await service.update_field(
                session,
                loaded_item.form_section.form_definition.study_version,
                loaded_item,
                FieldDefinitionUpdate(
                    label="Severity grade",
                    control_type="integer",
                    data_type="integer",
                    codelist_id=None,
                ),
                actor_id,
            )
            assert updated_item.label == "Severity grade"
            assert updated_item.control_type == "integer"
    finally:
        await engine.dispose()


async def test_subject_phase_associates_only_same_version_real_visits():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            visit_service = VisitDefinitionService()
            actor_id = uuid.uuid4()
            visit = await visit_service.define_visit(
                session,
                version,
                VisitDefinitionCreate(
                    name="Screening",
                    definition_kind="visit",
                    visit_number=1,
                    visit_type="scheduled",
                    display_order=1,
                ),
                actor_id,
            )
            folder = await visit_service.define_visit(
                session,
                version,
                VisitDefinitionCreate(
                    name="Visit folder",
                    definition_kind="folder",
                    display_order=2,
                ),
                actor_id,
            )

            phase_service = SubjectPhaseService()
            phase = await phase_service.create_phase_definition(
                session,
                design_version_id=version.id,
                name="Screening phase",
                phase_type=SubjectPhaseType.registered,
                display_order=1,
                visit_definition_ids=[visit.id],
                actor_id=actor_id,
            )
            assert phase.visit_definition_ids == [visit.id]
            assert phase.phase_type == SubjectPhaseType.registered

            with pytest.raises(ValidationError, match="cannot have associated visits"):
                await phase_service.create_phase_definition(
                    session,
                    design_version_id=version.id,
                    name="Arm selection",
                    phase_type=SubjectPhaseType.arm,
                    display_order=2,
                    visit_definition_ids=[visit.id],
                    actor_id=actor_id,
                )

            target_version = StudyVersion(
                study_id=version.study_id,
                version_number="2.0",
                status=StudyVersionStatus.draft,
            )
            session.add(target_version)
            await session.flush()
            counts = await DesignCloneService().clone_version(
                session,
                source_version_id=version.id,
                target_version_id=target_version.id,
            )
            cloned_phase = (await phase_service.list_phase_definitions(session, target_version.id))[
                0
            ]
            assert counts["subject_phase_visits"] == 1
            assert len(cloned_phase.visit_definition_ids) == 1
            assert cloned_phase.visit_definition_ids[0] != visit.id

            with pytest.raises(ValidationError):
                await phase_service.update_phase_definition(
                    session,
                    phase.id,
                    visit_definition_ids=[folder.id],
                    actor_id=actor_id,
                )
    finally:
        await engine.dispose()


async def test_folder_cycle_membership_and_soa_real_visit_guard():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            service = VisitDefinitionService()
            actor_id = uuid.uuid4()
            folder = await service.define_visit(
                session,
                version,
                VisitDefinitionCreate(
                    name="Treatment",
                    definition_kind="folder",
                    display_order=1,
                ),
                actor_id,
            )
            visit = await service.define_visit(
                session,
                version,
                VisitDefinitionCreate(
                    name="Cycle day 1",
                    definition_kind="visit",
                    visit_number=1,
                    visit_type="scheduled",
                    parent_folder_id=folder.id,
                    category="treatment",
                    subtype="ecoa",
                    display_order=2,
                ),
                actor_id,
            )
            cycle = await service.define_visit(
                session,
                version,
                VisitDefinitionCreate(
                    name="Treatment cycle",
                    definition_kind="cycle",
                    display_order=4,
                    repeat_min=1,
                    repeat_max=6,
                    cycle_length=28,
                ),
                actor_id,
            )
            cycle_visit = await service.define_cycle_visit(
                session,
                version,
                cycle,
                VisitDefinitionCreate(
                    name="Cycle day 8",
                    visit_number=8,
                    visit_type="scheduled",
                    category="treatment",
                    display_order=3,
                ),
                actor_id,
            )

            assert folder.definition_kind == "folder"
            assert visit.parent_folder_id == folder.id
            assert visit.category == "treatment"
            assert cycle_visit.definition_kind == "cycle_visit"
            assert (await service.cycle_memberships(session, version.id))[cycle.id] == [
                cycle_visit.id
            ]

            with pytest.raises(ValidationError) as member_exc:
                await service.update_definition(
                    session,
                    version,
                    cycle,
                    VisitDefinitionUpdate(member_visit_ids=[visit.id]),
                    actor_id,
                )
            assert member_exc.value.details == {"field": "member_visit_ids"}

            with pytest.raises(ValidationError) as orphan_exc:
                await service.define_visit(
                    session,
                    version,
                    VisitDefinitionCreate(
                        name="Orphan cycle visit",
                        definition_kind="cycle_visit",
                        visit_number=9,
                        display_order=5,
                    ),
                    actor_id,
                )
            assert orphan_exc.value.details["field"] == "definition_kind"

            soa_service = ScheduleOfAssessmentService()
            with pytest.raises(ValidationError) as exc:
                await soa_service.create_schedule_of_assessment(
                    session,
                    design_version_id=version.id,
                    entries=[
                        ScheduleEntryInput(
                            procedure_name="Vitals",
                            visit_definition_id=cycle.id,
                        )
                    ],
                    actor_id=actor_id,
                )
            assert exc.value.details["field"] == "visit_definition_id"

            soa = await soa_service.create_schedule_of_assessment(
                session,
                design_version_id=version.id,
                entries=[
                    ScheduleEntryInput(
                        procedure_name="Vitals",
                        visit_definition_id=visit.id,
                    ),
                    ScheduleEntryInput(
                        procedure_name="ECG",
                        visit_definition_id=cycle_visit.id,
                    ),
                ],
                actor_id=actor_id,
            )
            assert soa.entries[0].visit_definition_id == visit.id
            assert soa.entries[1].visit_definition_id == cycle_visit.id
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# arm_service / schedule_of_assessment_service — independent arm schedules
# ---------------------------------------------------------------------------


async def test_arm_is_simple_and_owns_an_independent_schedule():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            visit = await _make_visit(session, version.id, 1)
            arm = await ArmService().create_arm_definition(
                session,
                design_version_id=version.id,
                name="Arm A",
                display_order=1,
                actor_id=uuid.uuid4(),
            )
            soa_service = ScheduleOfAssessmentService()
            common = await soa_service.create_schedule_of_assessment(
                session,
                design_version_id=version.id,
                entries=[
                    ScheduleEntryInput(
                        procedure_name="Consent",
                        visit_definition_id=visit.id,
                    )
                ],
                actor_id=uuid.uuid4(),
            )
            schedule = await soa_service.create_schedule_of_assessment(
                session,
                design_version_id=version.id,
                arm_definition_id=arm.id,
                entries=[
                    ScheduleEntryInput(
                        procedure_name="Vitals",
                        visit_definition_id=visit.id,
                    )
                ],
                actor_id=uuid.uuid4(),
            )
            assert schedule.arm_definition_id == arm.id
            assert schedule.entries[0].visit_definition_id == visit.id
            assert (
                await soa_service.get_schedule_of_assessment(session, version.id)
            ).id == common.id
            assert (
                await soa_service.get_schedule_of_assessment(session, version.id, arm.id)
            ).id == schedule.id
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# crf_access_service — blinding
# ---------------------------------------------------------------------------


async def test_crf_blinded_with_unblind_role():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            access = await CrfAccessService().create_access_definition(
                session,
                design_version_id=version.id,
                role="Investigator",
                can_read=True,
                can_write=False,
                blinded=True,
                unblind_role="Unblinded Pharmacist",
                actor_id=uuid.uuid4(),
            )
            assert access.blinded is True
            assert access.unblind_role == "Unblinded Pharmacist"
    finally:
        await engine.dispose()


async def test_crf_unblind_role_without_blinded_rejected():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await CrfAccessService().create_access_definition(
                    session,
                    design_version_id=version.id,
                    role="Investigator",
                    can_read=True,
                    can_write=False,
                    blinded=False,
                    unblind_role="Pharmacist",
                    actor_id=uuid.uuid4(),
                )
            assert exc.value.details["field"] == "unblind_role"
    finally:
        await engine.dispose()


async def test_crf_access_and_coding_settings_can_be_listed_by_design_version():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            other_version = await _make_version(session)
            crf_service = CrfAccessService()
            coding_service = CodingSettingService()

            expected_access = await crf_service.create_access_definition(
                session,
                design_version_id=version.id,
                role="Investigator",
                can_read=True,
                can_write=False,
                actor_id=uuid.uuid4(),
            )
            await crf_service.create_access_definition(
                session,
                design_version_id=other_version.id,
                role="Monitor",
                can_read=True,
                can_write=True,
                actor_id=uuid.uuid4(),
            )
            expected_setting = await coding_service.create_coding_setting(
                session,
                design_version_id=version.id,
                dictionary_reference="MedDRA 27.0",
                coding_rule="Exact match",
                actor_id=uuid.uuid4(),
            )
            await coding_service.create_coding_setting(
                session,
                design_version_id=other_version.id,
                dictionary_reference="WHO Drug Global",
                actor_id=uuid.uuid4(),
            )

            access = await crf_service.list_access_definitions(session, version.id)
            settings = await coding_service.list_coding_settings(session, version.id)

            assert [item.id for item in access] == [expected_access.id]
            assert [item.id for item in settings] == [expected_setting.id]
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# raw_data_variable_service — label / suffix
# ---------------------------------------------------------------------------


async def test_raw_data_label_and_suffix_persist_and_strip():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            setting = await RawDataVariableService().create_variable_setting(
                session,
                design_version_id=version.id,
                name="AGE",
                data_type="integer",
                label="  Age in years  ",
                suffix="   ",  # whitespace-only -> None
                actor_id=uuid.uuid4(),
            )
            assert setting.label == "Age in years"
            assert setting.suffix is None
    finally:
        await engine.dispose()


async def test_raw_dataset_variables_include_fixed_and_special_field_companions():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            actor_id = uuid.uuid4()
            form_service = FormMetadataService()
            form = await form_service.create_form(
                session,
                version,
                FormDefinitionCreate(
                    name="Demographics", form_code="DM", display_order=1, domain="DM"
                ),
                actor_id,
            )
            section = await form_service.create_section(
                session,
                version,
                form,
                FormSectionCreate(name="Main", label="Main", display_order=1),
                actor_id,
            )
            severity = await form_service.create_field(
                session,
                version,
                section,
                FieldDefinitionCreate(
                    label="Severity",
                    variable_name="SEV",
                    control_type="radio",
                    data_type="string",
                    display_order=1,
                ),
                actor_id,
            )
            age = await form_service.create_field(
                session,
                version,
                section,
                FieldDefinitionCreate(
                    label="Age",
                    variable_name="AGE",
                    control_type="integer",
                    data_type="integer",
                    display_order=2,
                ),
                actor_id,
            )
            birth_date = await form_service.create_field(
                session,
                version,
                section,
                FieldDefinitionCreate(
                    label="Birth date",
                    variable_name="DOB",
                    control_type="date",
                    data_type="date",
                    display_order=3,
                ),
                actor_id,
            )

            raw_service = RawDataVariableService()
            datasets = await raw_service.build_dataset_definitions(session, version.id)
            names = [variable.name for variable in datasets[0].variables]
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
            assert {"SEV", "SEV_LABEL", "AGE", "AGE_NUM"}.issubset(names)
            assert {"DOB", "DOB_YEAR", "DOB_MONTH", "DOB_DAY"}.issubset(names)

            await raw_service.configure_field_setting(
                session,
                design_version_id=version.id,
                field_definition_id=severity.id,
                suffix="DECODE",
                actor_id=actor_id,
            )
            await raw_service.configure_field_setting(
                session,
                design_version_id=version.id,
                field_definition_id=age.id,
                suffix="STANDARD",
                actor_id=actor_id,
            )
            await raw_service.configure_field_setting(
                session,
                design_version_id=version.id,
                field_definition_id=birth_date.id,
                year_suffix="YYYY",
                month_suffix="MM",
                day_suffix="DD",
                actor_id=actor_id,
            )
            configured = await raw_service.build_dataset_definitions(session, version.id)
            configured_names = [variable.name for variable in configured[0].variables]
            assert "SEV_DECODE" in configured_names
            assert "AGE_STANDARD" in configured_names
            assert {"DOB_YYYY", "DOB_MM", "DOB_DD"}.issubset(configured_names)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# dependency services — happy path + guards
# ---------------------------------------------------------------------------


async def _make_form(session: AsyncSession, version_id: uuid.UUID, order: int) -> FormDefinition:
    form = FormDefinition(
        study_version_id=version_id,
        name=f"Form {order}",
        form_code=f"F{order:04d}",
        display_order=order,
    )
    session.add(form)
    await session.flush()
    return form


async def test_form_dependency_happy_path_and_guards():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            f1 = await _make_form(session, version.id, 1)
            f2 = await _make_form(session, version.id, 2)
            service = FormDependencyService()

            dep = await service.create_dependency(
                session,
                form_definition_id=f1.id,
                depends_on_form_definition_id=f2.id,
                actor_id=uuid.uuid4(),
            )
            assert dep.dependency_type == "prerequisite"

            # Self-dependency rejected.
            with pytest.raises(ValidationError):
                await service.create_dependency(
                    session,
                    form_definition_id=f1.id,
                    depends_on_form_definition_id=f1.id,
                )

            # Duplicate rejected.
            with pytest.raises(ConflictError):
                await service.create_dependency(
                    session,
                    form_definition_id=f1.id,
                    depends_on_form_definition_id=f2.id,
                )

            # Missing form rejected.
            with pytest.raises(NotFoundError):
                await service.create_dependency(
                    session,
                    form_definition_id=f1.id,
                    depends_on_form_definition_id=uuid.uuid4(),
                )
    finally:
        await engine.dispose()


async def test_visit_dependency_cross_version_rejected():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version_a = await _make_version(session)
            version_b = await _make_version(session)
            va = await _make_visit(session, version_a.id, 1)
            vb = await _make_visit(session, version_b.id, 1)
            service = VisitDependencyService()

            with pytest.raises(ValidationError):
                await service.create_dependency(
                    session,
                    visit_definition_id=va.id,
                    depends_on_visit_definition_id=vb.id,
                )

            # Self-dependency rejected.
            with pytest.raises(ValidationError):
                await service.create_dependency(
                    session,
                    visit_definition_id=va.id,
                    depends_on_visit_definition_id=va.id,
                )
    finally:
        await engine.dispose()
