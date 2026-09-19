"""Integration-boundary tests for CTMS monitoring and operational work.

These tests use an in-memory async SQLAlchemy database and deterministic local
fakes only. They verify that Phase 2 CTMS workflows share scope and traceability
metadata without crossing EDC ownership boundaries.

**Validates: Requirements 6.3-6.15, 7.5-7.12, 10.1-10.18, 12.1-12.5, 14.5**
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ConflictError
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.models.ctms.monitoring import (
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlanVersionStatus,
)
from app.models.ctms.work import (
    EscalationStatus,
    OperationalTask,
    OperationalTaskStatus,
    TaskDependency,
    TaskEscalation,
)
from app.models.identity import User, UserStatus
from app.models.lock import FreezeLock, FreezeLockType
from app.models.notification import Notification
from app.models.query import Query, QueryStatus, QueryTargetType
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitInstance, VisitInstanceStatus
from app.services import work_management_service as work_module
from app.services.lock_service import lock_service
from app.services.monitoring_service import MonitoringService
from app.services.work_management_service import WorkManagementService


@pytest.fixture
async def db_session() -> AsyncSession:
    """Provide a clean async local database for each boundary scenario."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _context(
    session: AsyncSession,
) -> tuple[User, User, Study, Site, StudyVersion, Subject, VisitInstance, Query]:
    actor = User(
        email=f"actor-{uuid4()}@example.test",
        first_name="CTMS",
        last_name="Actor",
        status=UserStatus.active,
    )
    cra = User(
        email=f"cra-{uuid4()}@example.test",
        first_name="Assigned",
        last_name="CRA",
        status=UserStatus.active,
    )
    session.add_all([actor, cra])
    await session.flush()

    study = Study(
        study_code=f"BOUNDARY-{uuid4()}",
        title="Monitoring boundary study",
        created_by=actor.id,
    )
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="001", name="Boundary site")
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        published_by=actor.id,
    )
    session.add_all([site, version])
    await session.flush()

    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="SUB-001",
        status=SubjectStatus.enrolled,
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()
    visit = VisitInstance(
        subject_id=subject.id,
        name="Week 4",
        visit_date=date(2025, 2, 1),
        window_status="in_window",
        status=VisitInstanceStatus.scheduled,
    )
    query = Query(
        study_id=study.id,
        site_id=site.id,
        subject_id=subject.id,
        target_type=QueryTargetType.subject.value,
        target_id=subject.id,
        text="Clinical source text must remain EDC-owned",
        status=QueryStatus.open,
        created_by=actor.id,
    )
    session.add_all([visit, query])
    await session.flush()
    return actor, cra, study, site, version, subject, visit, query


def _scoped_user(study_id, site_id):
    """Build a deterministic permission user without external role services."""

    permission = SimpleNamespace(code="ctms.monitoring-activity-management")
    role = SimpleNamespace(role_permissions=[SimpleNamespace(permission=permission)])
    assignment = SimpleNamespace(role=role, study_id=study_id, site_id=site_id)
    return SimpleNamespace(user_roles=[assignment], status=UserStatus.active)


async def _published_plan(
    session: AsyncSession,
    actor: User,
    study: Study,
    site: Site,
) -> tuple[MonitoringService, object, object]:
    service = MonitoringService()
    plan = await service.create_plan(
        session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        correlation_id="plan-boundary-create",
        payload={
            "name": "Risk-based monitoring",
            "objectives": "Protect participants and data quality",
            "activity_types": [MonitoringActivityType.ROUTINE_MONITORING.value],
        },
    )
    published = await service.publish_plan(
        session,
        plan,
        actor_id=actor.id,
        correlation_id="plan-boundary-publish",
    )
    return service, plan, published


@pytest.mark.asyncio
async def test_plan_amendment_and_cra_scope_share_the_boundary(
    db_session: AsyncSession,
):
    actor, cra, study, site, _version, _subject, _visit, _query = await _context(db_session)
    service, plan, published = await _published_plan(db_session, actor, study, site)

    with pytest.raises(ConflictError, match="immutable"):
        await service.update_plan(
            db_session,
            plan,
            {"name": "Direct published mutation"},
            actor_id=actor.id,
        )

    draft = await service.amend_plan(
        db_session,
        plan,
        {"cadence": "Every 4 weeks"},
        reason="Risk assessment changed",
        actor_id=actor.id,
        correlation_id="plan-boundary-amend",
    )
    assert draft.version_number == 2
    assert draft.status == MonitoringPlanVersionStatus.DRAFT.value
    assert draft.amendment_reason == "Risk assessment changed"
    assert published.status == MonitoringPlanVersionStatus.PUBLISHED.value
    assert published.cadence is None

    activity = await service.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        correlation_id="activity-boundary-create",
        payload={
            "activity_type": MonitoringActivityType.ROUTINE_MONITORING.value,
            "planned_date": datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
            "assigned_cra_id": actor.id,
        },
    )
    other_scope = _scoped_user(uuid4(), uuid4())
    with pytest.raises(AuthorizationError):
        await service.assign_activity(
            db_session,
            activity,
            cra.id,
            actor_id=actor.id,
            user=other_scope,
            correlation_id="activity-boundary-denied",
        )
    assert activity.assigned_cra_id == actor.id

    await db_session.commit()
    versions = await service.list_versions(db_session, plan)
    assert [(item.version_number, item.status) for item in versions] == [
        (1, MonitoringPlanVersionStatus.PUBLISHED.value),
        (2, MonitoringPlanVersionStatus.DRAFT.value),
    ]

    history = (
        await db_session.execute(
            select(CTMSStatusHistory).where(
                CTMSStatusHistory.entity_type == "monitoring_activity",
                CTMSStatusHistory.entity_id == activity.id,
            )
        )
    ).scalars().all()
    assert history
    assert all(item.study_id == study.id and item.site_id == site.id for item in history)
    assert all(item.changed_by == actor.id for item in history)


@pytest.mark.asyncio
async def test_monitoring_follow_up_preserves_query_and_propagates_trace_metadata(
    db_session: AsyncSession,
):
    actor, cra, study, site, _version, _subject, _visit, query = await _context(db_session)
    monitoring, plan, _published = await _published_plan(db_session, actor, study, site)
    activity = await monitoring.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        correlation_id="monitoring-follow-up-correlation",
        payload={
            "activity_type": MonitoringActivityType.ROUTINE_MONITORING.value,
            "planned_date": datetime(2025, 3, 2, 10, 0, tzinfo=UTC),
            "assigned_cra_id": cra.id,
            "issue_reference": "monitoring-follow-up-17",
        },
    )

    original_query = (query.status, query.text, query.updated_at)
    work = WorkManagementService()
    task = await work.create_query_follow_up(
        db_session,
        query_id=query.id,
        actor_id=actor.id,
        owner_id=cra.id,
        title="Monitoring follow-up",
        approved_summary="Review operational evidence only",
        correlation_id="work-follow-up-correlation",
    )
    await db_session.commit()

    assert activity.study_id == task.study_id == study.id
    assert activity.site_id == task.site_id == site.id
    assert str(task.correlation_id) != ""
    assert task.query_id == query.id
    assert task.description == "Operational follow-up for an EDC Query"
    assert task.query_summary == "Review operational evidence only"
    assert "Clinical source text" not in repr(task)
    assert not hasattr(task, "clinical_data")
    assert (query.status, query.text, query.updated_at) == original_query

    histories = (
        await db_session.execute(
            select(CTMSStatusHistory).where(
                CTMSStatusHistory.entity_id.in_([activity.id, task.id])
            )
        )
    ).scalars().all()
    assert histories
    assert all(item.study_id == study.id and item.site_id == site.id for item in histories)

    audits = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_id.in_([activity.id, task.id]),
                AuditEvent.module == "CTMS",
            )
        )
    ).scalars().all()
    assert audits
    assert all(item.actor_id == actor.id for item in audits)
    assert all(item.study_id == study.id and item.site_id == site.id for item in audits)
    assert all(item.correlation_id for item in audits)

    outbox = (
        await db_session.execute(
            select(CTMSOutbox).where(CTMSOutbox.aggregate_id.in_([activity.id, task.id]))
        )
    ).scalars().all()
    assert outbox
    assert all(item.module == "CTMS" for item in outbox)
    assert all(item.correlation_id for item in outbox)

    notifications = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == cra.id)
        )
    ).scalars().all()
    assert any(item.type == "ctms_task_assigned" for item in notifications)
    assert all(item.module == "CTMS" for item in notifications)
    assert all(item.study_id == study.id and item.site_id == site.id for item in notifications)
    assert all(item.correlation_id for item in notifications)


@pytest.mark.asyncio
async def test_frozen_and_locked_protocol_visit_remains_unchanged_after_monitoring(
    db_session: AsyncSession,
):
    actor, cra, study, site, _version, subject, visit, _query = await _context(db_session)
    monitoring, plan, _published = await _published_plan(db_session, actor, study, site)
    visit_snapshot = {
        "subject_id": visit.subject_id,
        "visit_date": visit.visit_date,
        "window_status": visit.window_status,
        "status": visit.status,
        "study_version_id": subject.study_version_id,
        "subject_status": subject.status,
    }

    await lock_service.freeze(db_session, visit, actor.id)
    await lock_service.lock(db_session, visit, actor.id)
    activity = await monitoring.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        correlation_id="locked-visit-monitoring",
        payload={
            "activity_type": MonitoringActivityType.REMOTE_REVIEW.value,
            "planned_date": datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
            "assigned_cra_id": cra.id,
            "edc_visit_instance_id": visit.id,
        },
    )
    completed = await monitoring.complete_activity(
        db_session,
        activity,
        evidence={"report_reference": "operational-report-17"},
        notes="Completed independently of the protocol visit",
        actor_id=cra.id,
        correlation_id="locked-visit-monitoring-complete",
    )
    await db_session.commit()

    assert completed.status == MonitoringActivityStatus.COMPLETED.value
    assert completed.edc_visit_instance_id == visit.id
    assert {
        (item.lock_type, item.is_active)
        for item in (
            await db_session.execute(
                select(FreezeLock).where(
                    FreezeLock.object_type == "visit",
                    FreezeLock.object_id == visit.id,
                )
            )
        ).scalars().all()
    } == {
        (FreezeLockType.freeze.value, True),
        (FreezeLockType.lock.value, True),
    }

    persisted_visit = await db_session.get(VisitInstance, visit.id)
    persisted_subject = await db_session.get(Subject, subject.id)
    assert persisted_visit is not None and persisted_subject is not None
    assert {
        "subject_id": persisted_visit.subject_id,
        "visit_date": persisted_visit.visit_date,
        "window_status": persisted_visit.window_status,
        "status": persisted_visit.status,
        "study_version_id": persisted_subject.study_version_id,
        "subject_status": persisted_subject.status,
    } == visit_snapshot


@pytest.mark.asyncio
async def test_dependencies_escalations_and_notification_failure_are_isolated(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    actor, owner, study, site, _version, _subject, _visit, _query = await _context(db_session)
    work = WorkManagementService(escalations_enabled=True)

    prerequisite = await work.create_task(
        db_session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Collect monitoring evidence",
        owner_id=owner.id,
        correlation_id="dependency-prerequisite",
    )
    dependent = await work.create_task(
        db_session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Review monitoring evidence",
        owner_id=owner.id,
        correlation_id="dependency-dependent",
    )
    dependency = await work.add_dependency(
        db_session,
        dependent,
        prerequisite,
        actor.id,
        reason="Evidence must be collected first",
        correlation_id="dependency-link",
    )
    assert dependency.task_id == dependent.id
    assert dependent.status == OperationalTaskStatus.BLOCKED.value

    escalation = await work.create_escalation(
        db_session,
        {"task_id": dependent.id, "owner_id": owner.id, "reason": "Review is blocked"},
        actor.id,
        correlation_id="escalation-create",
    )
    await work.transition_escalation_status(
        db_session,
        escalation,
        EscalationStatus.RESOLVED,
        actor.id,
        reason="Prerequisite owner acknowledged",
        correlation_id="escalation-resolve",
    )
    await work.transition_task_status(
        db_session,
        prerequisite,
        OperationalTaskStatus.COMPLETED,
        actor.id,
        reason="Evidence collected",
        correlation_id="dependency-complete",
    )
    assert dependent.status == OperationalTaskStatus.OPEN.value
    assert escalation.status == EscalationStatus.RESOLVED.value

    failed_deliveries: list[dict[str, object]] = []

    async def failed_notification_delivery(session, *, user_ids, notification_type, payload, **kwargs):
        del session
        failed_deliveries.append(
            {"user_ids": user_ids, "notification_type": notification_type, "payload": payload, **kwargs}
        )
        return []

    monkeypatch.setattr(
        work_module.notification_service,
        "create_ctms_notification",
        failed_notification_delivery,
    )
    isolated_task = await work.create_task(
        db_session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Persist despite notification delivery failure",
        owner_id=owner.id,
        correlation_id="notification-failure-isolated",
    )
    await db_session.commit()

    persisted = await db_session.get(OperationalTask, isolated_task.id)
    assert persisted is not None
    assert failed_deliveries
    assert failed_deliveries[-1]["notification_type"] == "ctms_task_assigned"
    assert failed_deliveries[-1]["study_id"] == study.id
    assert failed_deliveries[-1]["site_id"] == site.id

    task_audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "operational_task",
                AuditEvent.entity_id == isolated_task.id,
            )
        )
    ).scalars().all()
    task_outbox = (
        await db_session.execute(
            select(CTMSOutbox).where(CTMSOutbox.aggregate_id == isolated_task.id)
        )
    ).scalars().all()
    assert task_audit and task_outbox
    assert not (
        await db_session.execute(
            select(Notification).where(
                Notification.type == "ctms_task_assigned",
                Notification.correlation_id == "notification-failure-isolated",
            )
        )
    ).scalars().all()
    assert len((await db_session.execute(select(TaskDependency))).scalars().all()) == 1
    assert len((await db_session.execute(select(TaskEscalation))).scalars().all()) == 1
