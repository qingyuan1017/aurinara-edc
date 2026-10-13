"""Focused coverage for CTMS operational study planning and lifecycle."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.models.ctms.operational_study import (
    OperationalStudyStatus,
    StudyOperationalMilestone,
)
from app.models.ctms.reference_data import CTMSReferenceValue, ReferenceCategory
from app.models.edc.study import Study, StudyVersion, StudyVersionStatus
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import Role, ScopeLevel, User, UserRole, UserStatus
from app.schemas.ctms.study import OperationalStudyResponse
from app.services.ctms.ctms_ownership_guard import CTMSOwnershipError
from app.services.ctms.operational_study_service import OperationalStudyService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _canonical_study(session: AsyncSession) -> tuple[User, Study, StudyVersion]:
    actor = User(
        email=f"ctms-study-{uuid4()}@example.test",
        first_name="CTMS",
        last_name="Operator",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(
        study_code=f"CTMS-STUDY-{uuid4()}",
        title="Clinical study",
        sponsor="Platform Sponsor",
        created_by=actor.id,
    )
    session.add(study)
    await session.flush()
    version = StudyVersion(study_id=study.id, version_number="1.0", status=StudyVersionStatus.draft)
    session.add(version)
    await session.flush()
    return actor, study, version


@pytest.mark.asyncio
async def test_operational_study_planning_lifecycle_is_atomic_and_clinically_independent(
    db_session: AsyncSession,
):
    actor, study, version = await _canonical_study(db_session)
    clinical_snapshot = (study.title, study.status, version.version_number, version.status)
    service = OperationalStudyService()

    profile = await service.create_profile(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={
            "phase": "Phase II",
            "study_type": "Interventional",
            "main_purpose": "Treatment",
            "therapeutic_area": "Oncology",
            "indication": "Example indication",
            "blind_method": "Double blind",
            "randomized": True,
            "expected_subject_count": 120,
            "language": "English",
            "expected_site_count": 12,
            "construction_period": "24 months",
            "planned_start_date": "2027-01-01",
            "planned_end_date": "2028-12-31",
            "study_currency": "USD",
            "planning_metadata": {"region": "Global"},
            "readiness_criteria": {"minimum_sites": 3},
        },
        correlation_id="study-create-1",
    )
    await service.create_study_plan(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={
            "title": "Startup plan",
            "objective": "Open sites",
            "planning_scope": {"region": "Global"},
        },
        correlation_id="plan-create-1",
    )
    await service.create_enrollment_plan(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={"title": "Enrollment plan", "target_quantity": 120},
        correlation_id="enrollment-plan-1",
    )
    await service.create_readiness_criterion(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={"name": "Regulatory package", "required": True},
        correlation_id="criterion-1",
    )
    milestone = await service.create_operational_milestone(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={"title": "First site ready", "milestone_type": "Site startup"},
        correlation_id="milestone-1",
    )
    assert isinstance(milestone, StudyOperationalMilestone)
    assert profile.study_name == "Clinical study"
    assert profile.sponsor == "Platform Sponsor"
    response = OperationalStudyResponse.model_validate(profile)
    assert response.study_name == "Clinical study"
    assert response.sponsor == "Platform Sponsor"

    for status, reason in (
        (OperationalStudyStatus.PLANNING, "Planning approved"),
        (OperationalStudyStatus.READY, "Readiness criteria reviewed"),
        (OperationalStudyStatus.ACTIVE, "Operational launch approved"),
    ):
        await service.transition_status(
            db_session,
            profile,
            status,
            reason=reason,
            actor_id=actor.id,
            correlation_id=f"transition-{status.value}",
        )
    await service.update_profile(
        db_session,
        profile,
        {"planning_metadata": {"region": "Global", "owner_group": "Operations"}},
        actor_id=actor.id,
        reason="Active planning metadata clarified",
        correlation_id="study-update-1",
    )
    await service.archive_study(
        db_session,
        profile,
        actor_id=actor.id,
        reason="Operational study retired",
        correlation_id="study-archive-1",
    )

    assert profile.retention_state == "archived"
    assert profile.archived_at is not None
    assert (study.title, study.status, version.version_number, version.status) == clinical_snapshot

    history = (
        (
            await db_session.execute(
                select(CTMSStatusHistory).where(CTMSStatusHistory.entity_id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    assert [entry.status for entry in history] == ["Draft", "Planning", "Ready", "Active"]
    assert history[0].reason is None
    assert all(entry.reason for entry in history[1:])
    audit_count = await db_session.scalar(
        select(func.count(AuditEvent.id)).where(AuditEvent.module == "CTMS")
    )
    outbox_count = await db_session.scalar(
        select(func.count(CTMSOutbox.id)).where(CTMSOutbox.module == "CTMS")
    )
    assert audit_count == 10
    assert outbox_count == 10


@pytest.mark.asyncio
async def test_active_study_changes_require_reason_and_clinical_fields_are_rejected(
    db_session: AsyncSession,
):
    actor, study, version = await _canonical_study(db_session)
    service = OperationalStudyService()
    profile = await service.create_profile(db_session, study_id=study.id, actor_id=actor.id)
    await service.transition_status(
        db_session, profile, "Planning", reason="Planning started", actor_id=actor.id
    )
    await service.transition_status(
        db_session, profile, "Ready", reason="Readiness approved", actor_id=actor.id
    )
    await service.transition_status(
        db_session, profile, "Active", reason="Launch approved", actor_id=actor.id
    )

    with pytest.raises(ValidationError):
        await service.update_profile(
            db_session, profile, {"planning_metadata": {"owner": "Operations"}}, actor_id=actor.id
        )

    with pytest.raises(CTMSOwnershipError):
        await service.update_profile(
            db_session,
            profile,
            {"study_version_id": version.id},
            actor_id=actor.id,
            reason="Attempted clinical change",
        )
    assert study.status.value == "Draft"
    assert version.status.value == "draft"


@pytest.mark.asyncio
async def test_project_milestones_require_matching_activity_scope_and_scoped_assignees(
    db_session: AsyncSession,
):
    actor, study, _version = await _canonical_study(db_session)
    role = Role(name=f"CRA-{uuid4()}", scope_level=ScopeLevel.study)
    db_session.add(role)
    await db_session.flush()
    db_session.add(
        UserRole(
            user_id=actor.id,
            role_id=role.id,
            study_id=study.id,
            assigned_by=actor.id,
        )
    )
    await db_session.flush()
    service = OperationalStudyService()
    db_session.add(
        CTMSReferenceValue(
            category=ReferenceCategory.PROJECT_STATUS.value,
            code="READY",
            label="Ready for Work",
            sort_order=5,
        )
    )
    await db_session.flush()

    country_milestone = await service.create_operational_milestone(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={
            "title": "Country startup complete",
            "description": "All countries by default",
            "milestone_type": "Site startup",
            "scope_level": "country",
        },
    )
    activity = await service.create_study_plan(
        db_session,
        study_id=study.id,
        actor_id=actor.id,
        payload={
            "title": "Prepare startup packages",
            "milestone_id": country_milestone.id,
            "scope_level": "country",
            "assignee_role_id": role.id,
            "assignee_user_id": actor.id,
        },
    )

    assert country_milestone.country_code is None
    assert activity.milestone_id == country_milestone.id
    assert activity.status == "READY"
    assert activity.assignee_role_id == role.id
    assert activity.assignee_user_id == actor.id

    with pytest.raises(ValidationError, match="scope must match"):
        await service.create_study_plan(
            db_session,
            study_id=study.id,
            actor_id=actor.id,
            payload={
                "title": "Invalid study activity",
                "milestone_id": country_milestone.id,
                "scope_level": "study",
            },
        )

    with pytest.raises(ValidationError, match="linked master activities"):
        await service.update_operational_milestone(
            db_session,
            country_milestone.id,
            {"scope_level": "study", "reason": "Attempt scope change"},
            actor=actor,
        )
