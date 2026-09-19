"""Focused behavior coverage for CTMS Monitoring_Service."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.models.ctms.monitoring import (
    MonitoringActivityScheduleHistory,
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlanVersionStatus,
)
from app.models.identity import User, UserStatus
from app.models.site import Site
from app.models.study import Study
from app.services.monitoring_service import MonitoringService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _scope(session: AsyncSession) -> tuple[User, Study, Site]:
    actor = User(
        email="monitoring-service@example.test",
        first_name="Monitoring",
        last_name="CRA",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(study_code="MON-SVC-1", title="Monitoring service", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="001", name="Monitoring site")
    session.add(site)
    await session.flush()
    return actor, study, site


@pytest.mark.asyncio
async def test_plan_publication_amendment_and_activity_lifecycle_are_atomic(
    db_session: AsyncSession,
):
    actor, study, site = await _scope(db_session)
    service = MonitoringService()
    plan = await service.create_plan(
        db_session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        correlation_id="monitor-plan-create",
        payload={
            "name": "Risk-based monitoring",
            "objectives": "Protect participants and data quality",
            "activity_types": [MonitoringActivityType.ROUTINE_MONITORING.value],
            "cadence": "Every 8 weeks",
        },
    )
    published = await service.publish_plan(
        db_session, plan, actor_id=actor.id, correlation_id="monitor-plan-publish"
    )
    assert published.status == MonitoringPlanVersionStatus.PUBLISHED.value
    assert published.published_at is not None

    with pytest.raises(ConflictError, match="immutable"):
        await service.update_plan(
            db_session,
            plan,
            {"name": "Unauthorized published edit"},
            actor_id=actor.id,
        )

    draft = await service.amend_plan(
        db_session,
        plan,
        {"cadence": "Every 4 weeks"},
        reason="Risk assessment changed",
        actor_id=actor.id,
        correlation_id="monitor-plan-amend",
    )
    assert draft.version_number == 2
    assert draft.status == MonitoringPlanVersionStatus.DRAFT.value
    assert draft.amendment_reason == "Risk assessment changed"
    assert published.status == MonitoringPlanVersionStatus.PUBLISHED.value
    assert published.cadence == "Every 8 weeks"

    activity = await service.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        correlation_id="monitor-activity-schedule",
        payload={
            "activity_type": MonitoringActivityType.ROUTINE_MONITORING.value,
            "planned_date": datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            "assigned_cra_id": actor.id,
            "issue_reference": "issue-17",
            "escalation_reference": "escalation-4",
        },
    )
    assert activity.status == MonitoringActivityStatus.SCHEDULED.value
    assert activity.study_id == study.id
    assert activity.site_id == site.id

    await service.reschedule_activity(
        db_session,
        activity,
        datetime(2026, 2, 8, 10, 0, tzinfo=UTC),
        reason="CRA availability",
        actor_id=actor.id,
        correlation_id="monitor-activity-reschedule",
    )
    completed = await service.complete_activity(
        db_session,
        activity,
        evidence={"reference": "evidence://visit-report"},
        notes="Report reviewed",
        actor_id=actor.id,
        correlation_id="monitor-activity-complete",
    )
    assert completed.status == MonitoringActivityStatus.COMPLETED.value
    assert completed.completed_by == actor.id
    assert completed.completed_at is not None

    history = list(
        (
            await db_session.execute(
                select(MonitoringActivityScheduleHistory).where(
                    MonitoringActivityScheduleHistory.activity_id == activity.id
                )
            )
        ).scalars()
    )
    assert len(history) == 2
    assert history[1].previous_planned_date.replace(tzinfo=UTC) == datetime(
        2026, 2, 1, 10, 0, tzinfo=UTC
    )

    status_history = list(
        (
            await db_session.execute(
                select(CTMSStatusHistory).where(CTMSStatusHistory.entity_id == activity.id)
            )
        ).scalars()
    )
    outbox = list(
        (
            await db_session.execute(
                select(CTMSOutbox).where(CTMSOutbox.aggregate_id == activity.id)
            )
        ).scalars()
    )
    assert len(status_history) >= 3
    assert len(outbox) >= 3


@pytest.mark.asyncio
async def test_cancellation_requires_reason_and_allows_protocol_independent_operation(
    db_session: AsyncSession,
):
    actor, study, site = await _scope(db_session)
    service = MonitoringService()
    plan = await service.create_plan(
        db_session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        payload={
            "name": "Remote review plan",
            "activity_types": [MonitoringActivityType.REMOTE_REVIEW.value],
        },
    )
    await service.publish_plan(db_session, plan, actor_id=actor.id)
    activity = await service.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        payload={
            "activity_type": MonitoringActivityType.REMOTE_REVIEW.value,
            "planned_date": datetime(2026, 3, 1, tzinfo=UTC),
            "assigned_cra_id": actor.id,
        },
    )
    with pytest.raises(ValidationError):
        await service.cancel_activity(db_session, activity, actor_id=actor.id)
    cancelled = await service.cancel_activity(
        db_session,
        activity,
        reason="Site unavailable",
        actor_id=actor.id,
    )
    assert cancelled.status == MonitoringActivityStatus.CANCELLED.value
    assert cancelled.cancelled_by == actor.id
    assert cancelled.cancellation_reason == "Site unavailable"


@pytest.mark.asyncio
async def test_monitoring_rejects_clinical_mutation_payload_before_state_change(
    db_session: AsyncSession,
):
    actor, study, site = await _scope(db_session)
    service = MonitoringService()
    plan = await service.create_plan(
        db_session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        payload={
            "name": "Boundary plan",
            "activity_types": [MonitoringActivityType.SITE_INITIATION.value],
        },
    )
    await service.publish_plan(db_session, plan, actor_id=actor.id)
    with pytest.raises(ConflictError, match="EDC-owned"):
        await service.schedule_activity(
            db_session,
            plan=plan,
            actor_id=actor.id,
            payload={
                "activity_type": MonitoringActivityType.SITE_INITIATION.value,
                "planned_date": datetime(2026, 4, 1, tzinfo=UTC),
                "clinical_data": {"value": "must never be stored"},
            },
        )
    assert (
        await db_session.scalar(
            select(CTMSOutbox).where(CTMSOutbox.event_type == "schedule")
        )
    ) is None
