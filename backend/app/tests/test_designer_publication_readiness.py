"""Integration tests for Designer publication readiness and amendment cloning."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.designer.study_versions import (
    abandon_version,
    publish_version,
    validate_version_for_publication,
)
from app.core.database import Base
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.schedule_of_assessment import (
    ScheduleOfAssessment,
    ScheduleOfAssessmentEntry,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.subject_phase_definition import (
    SubjectPhaseDefinition,
    SubjectPhaseType,
)
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.schemas.designer.study_version import StudyVersionAbandon
from app.services.designer.design_clone_service import DesignCloneService
from app.services.designer.design_validation_service import DesignValidationService
from app.services.designer.subject_phase_service import subject_phase_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _make_version(
    session: AsyncSession, *, status: StudyVersionStatus = StudyVersionStatus.draft
) -> StudyVersion:
    study = Study(
        study_code=f"READY-{uuid.uuid4().hex[:8]}",
        title="Publication Readiness Study",
        status=StudyStatus.draft,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=status,
    )
    session.add(version)
    await session.flush()
    return version


async def _add_minimal_complete_design(
    session: AsyncSession,
    version: StudyVersion,
    *,
    seed_subject_phases: bool = True,
) -> None:
    codelist = Codelist(study_version_id=version.id, name="Yes / No", code="YN")
    visit = VisitDefinition(
        study_version_id=version.id,
        name="Screening",
        visit_number=1,
        visit_type="screening",
        target_day=0,
        window_before=7,
        window_after=0,
        display_order=1,
        is_required=True,
    )
    form = FormDefinition(
        study_version_id=version.id,
        name="Eligibility",
        form_code="IE",
        display_order=1,
        is_repeating=False,
    )
    session.add_all([codelist, visit, form])
    await session.flush()

    item = CodelistItem(codelist_id=codelist.id, code="Y", label="Yes", display_order=1)
    section = FormSection(form_definition_id=form.id, name="Main", display_order=1)
    session.add_all([item, section])
    await session.flush()
    field = FieldDefinition(
        form_section_id=section.id,
        label="Eligible?",
        variable_name="ELIG",
        control_type="radio",
        data_type="string",
        is_required=True,
        codelist_id=codelist.id,
        display_order=1,
    )
    schedule = ScheduleOfAssessment(design_version_id=version.id)
    session.add_all([field, schedule])
    await session.flush()
    rule = EditCheck(
        study_version_id=version.id,
        name="Eligibility required",
        rule_json={"field": str(field.id), "operator": "not_null"},
        severity="error",
        is_active=True,
    )
    session.add(rule)
    await session.flush()
    session.add(
        ScheduleOfAssessmentEntry(
            schedule_of_assessment_id=schedule.id,
            form_definition_id=form.id,
            visit_definition_id=visit.id,
            display_order=1,
        )
    )
    await session.flush()
    if seed_subject_phases:
        await subject_phase_service.seed_default_phase_flow(
            session,
            design_version_id=version.id,
            study_id=version.study_id,
        )


async def test_readiness_blocks_empty_design_with_actionable_issues():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            report = await DesignValidationService().validate(session, version)

            assert report.valid is False
            assert {issue.code for issue in report.issues if issue.severity == "error"} >= {
                "NO_FORMS",
                "NO_VISITS",
                "NO_SCHEDULE_OF_ASSESSMENT",
                "NO_SUBJECT_PHASES",
            }
    finally:
        await engine.dispose()


async def test_readiness_accepts_complete_vertical_slice():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            await _add_minimal_complete_design(session, version)

            report = await DesignValidationService().validate(session, version)

            assert report.valid is True
            assert report.counts.forms == 1
            assert report.counts.fields == 1
            assert report.counts.visits == 1
            assert report.counts.scheduled_form_mappings == 1
    finally:
        await engine.dispose()


async def test_readiness_requires_registered_subject_phase():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            await _add_minimal_complete_design(
                session,
                version,
                seed_subject_phases=False,
            )
            session.add(
                SubjectPhaseDefinition(
                    design_version_id=version.id,
                    name="Treatment",
                    phase_type=SubjectPhaseType.common,
                    display_order=1,
                )
            )
            await session.flush()

            report = await DesignValidationService().validate(session, version)

            assert report.valid is False
            assert "NO_REGISTERED_SUBJECT_PHASE" in {
                issue.code for issue in report.issues if issue.severity == "error"
            }
    finally:
        await engine.dispose()


async def test_readiness_accepts_boolean_checkbox_without_codelist():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            await _add_minimal_complete_design(session, version)
            field = (
                await session.execute(
                    select(FieldDefinition)
                    .join(FormSection)
                    .join(FormDefinition)
                    .where(FormDefinition.study_version_id == version.id)
                )
            ).scalar_one()
            field.control_type = "checkbox"
            field.data_type = "boolean"
            field.codelist_id = None
            await session.flush()

            report = await DesignValidationService().validate(session, version)

            assert report.valid is True
            assert "FIELD_CODELIST_REQUIRED" not in {issue.code for issue in report.issues}
    finally:
        await engine.dispose()


async def test_readiness_requires_schedule_for_each_treatment_arm():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            await _add_minimal_complete_design(session, version)
            arm = ArmDefinition(
                study_version_id=version.id,
                name="Arm A",
                display_order=1,
            )
            session.add(arm)
            await session.flush()

            report = await DesignValidationService().validate(session, version)

            assert "ARM_HAS_NO_SCHEDULE" in {issue.code for issue in report.issues}
            assert report.valid is False

            form_id = (
                await session.execute(
                    select(FormDefinition.id).where(FormDefinition.study_version_id == version.id)
                )
            ).scalar_one()
            visit_id = (
                await session.execute(
                    select(VisitDefinition.id).where(VisitDefinition.study_version_id == version.id)
                )
            ).scalar_one()
            arm_schedule = ScheduleOfAssessment(
                design_version_id=version.id,
                arm_definition_id=arm.id,
            )
            session.add(arm_schedule)
            await session.flush()
            session.add(
                ScheduleOfAssessmentEntry(
                    schedule_of_assessment_id=arm_schedule.id,
                    form_definition_id=form_id,
                    visit_definition_id=visit_id,
                    display_order=1,
                )
            )
            await session.flush()

            ready = await DesignValidationService().validate(session, version)
            assert "ARM_HAS_NO_SCHEDULE" not in {issue.code for issue in ready.issues}
            assert ready.valid is True
    finally:
        await engine.dispose()


async def test_amendment_clone_rebinds_the_complete_casebook_graph():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            source = await _make_version(session, status=StudyVersionStatus.published)
            await _add_minimal_complete_design(session, source)
            target = StudyVersion(
                study_id=source.study_id,
                version_number="2.0",
                status=StudyVersionStatus.draft,
                amended_from_version_id=source.id,
                amendment_reason="UAT correction",
            )
            session.add(target)
            await session.flush()

            counts = await DesignCloneService().clone_version(
                session,
                source_version_id=source.id,
                target_version_id=target.id,
            )

            cloned_form = (
                await session.execute(
                    select(FormDefinition).where(FormDefinition.study_version_id == target.id)
                )
            ).scalar_one()
            cloned_section = (
                await session.execute(
                    select(FormSection).where(FormSection.form_definition_id == cloned_form.id)
                )
            ).scalar_one()
            cloned_field = (
                await session.execute(
                    select(FieldDefinition).where(
                        FieldDefinition.form_section_id == cloned_section.id
                    )
                )
            ).scalar_one()
            cloned_codelist = (
                await session.execute(
                    select(Codelist).where(Codelist.study_version_id == target.id)
                )
            ).scalar_one()
            cloned_visit = (
                await session.execute(
                    select(VisitDefinition).where(VisitDefinition.study_version_id == target.id)
                )
            ).scalar_one()
            cloned_schedule = (
                await session.execute(
                    select(ScheduleOfAssessment).where(
                        ScheduleOfAssessment.design_version_id == target.id
                    )
                )
            ).scalar_one()
            cloned_entry = (
                await session.execute(
                    select(ScheduleOfAssessmentEntry).where(
                        ScheduleOfAssessmentEntry.schedule_of_assessment_id == cloned_schedule.id
                    )
                )
            ).scalar_one()
            cloned_rule = (
                await session.execute(
                    select(EditCheck).where(EditCheck.study_version_id == target.id)
                )
            ).scalar_one()

            assert counts["forms"] == 1
            assert counts["schedule_entries"] == 1
            assert (
                cloned_form.id
                != (
                    await session.execute(
                        select(FormDefinition.id).where(
                            FormDefinition.study_version_id == source.id
                        )
                    )
                ).scalar_one()
            )
            assert cloned_field.codelist_id == cloned_codelist.id
            assert cloned_entry.form_definition_id == cloned_form.id
            assert cloned_entry.visit_definition_id == cloned_visit.id
            assert cloned_rule.rule_json["field"] == str(cloned_field.id)

            report = await DesignValidationService().validate(session, target)
            assert report.valid is True
    finally:
        await engine.dispose()


async def test_readiness_route_authorizes_against_the_owning_study():
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    user = MagicMock()
    permission_service = MagicMock()
    report = MagicMock()

    with (
        patch(
            "app.api.routes.designer.study_versions.study_version_service.get_version",
            new=AsyncMock(return_value=version),
        ),
        patch(
            "app.api.routes.designer.study_versions.design_validation_service.validate",
            new=AsyncMock(return_value=report),
        ),
    ):
        result = await validate_version_for_publication(
            version.id,
            AsyncMock(),
            user,
            permission_service,
        )

    assert result is report
    permission_service.require.assert_called_once_with(
        user,
        "designer.study_version.read",
        study_id=version.study_id,
    )


async def test_publish_scope_denial_happens_before_design_mutation():
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    user = MagicMock()
    permission_service = MagicMock()
    permission_service.require.side_effect = PermissionError("out of scope")

    with (
        patch(
            "app.api.routes.designer.study_versions.study_version_service.get_version",
            new=AsyncMock(return_value=version),
        ),
        patch(
            "app.api.routes.designer.study_versions.study_version_service.publish",
            new=AsyncMock(),
        ) as publish,
        pytest.raises(PermissionError, match="out of scope"),
    ):
        await publish_version(
            version.id,
            AsyncMock(),
            user,
            permission_service,
        )

    permission_service.require.assert_called_once_with(
        user,
        "designer.version.publish",
        study_id=version.study_id,
    )
    publish.assert_not_awaited()


async def test_abandon_scope_denial_happens_before_design_mutation():
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    user = MagicMock()
    permission_service = MagicMock()
    permission_service.require.side_effect = PermissionError("out of scope")

    with (
        patch(
            "app.api.routes.designer.study_versions.study_version_service.get_version",
            new=AsyncMock(return_value=version),
        ),
        patch(
            "app.api.routes.designer.study_versions.study_version_service.abandon_draft",
            new=AsyncMock(),
        ) as abandon,
        pytest.raises(PermissionError, match="out of scope"),
    ):
        await abandon_version(
            version.id,
            StudyVersionAbandon(reason="Superseded draft"),
            AsyncMock(),
            user,
            permission_service,
        )

    permission_service.require.assert_called_once_with(
        user,
        "designer.study_version.amend",
        study_id=version.study_id,
    )
    abandon.assert_not_awaited()
