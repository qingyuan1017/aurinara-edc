"""Phase 2 CTMS qualification gate.

This suite composes the Phase 2 services at their database boundary rather
than repeating the individual property tests.  It intentionally exercises the
qualification cases called out by task 7.2: monitoring/version ownership,
EDC visit separation, work/query follow-ups, operational attachments,
projection minimization, outbox delivery, duplicate/stale delivery,
transaction rollback, notifications, and worker outage/backpressure.

**Validates: Requirements 6.1-6.15, 7.1-7.12, 8.1-8.12, 9.1-9.18,
12.6-12.7, 13.8-13.16, 14.2, 14.7**
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.ctms import Module
from app.core.database import Base
from app.core.exceptions import AuthorizationError, ConflictError
from app.models.audit import AuditEvent
from app.models.ctms.coordination import (
    CoordinationEvent,
    CoordinationEventLog,
    CTMSOutbox,
    CTMSStatusHistory,
)
from app.models.ctms.monitoring import (
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlanVersionStatus,
)
from app.models.ctms.ownership import ProjectionType
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.file_attachment import FileAttachment, FileAttachmentObjectType
from app.models.identity import User, UserStatus
from app.models.lock import FreezeLock, FreezeLockType
from app.models.notification import NotificationStatus
from app.models.query import Query, QueryStatus, QueryTargetType
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitInstance, VisitInstanceStatus
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.coordination_service import BoundedCoordinationQueue, CoordinationService
from app.services.ctms_projection_service import CTMSProjectionService
from app.services.file_attachment_service import FileAttachmentService
from app.services.monitoring_service import MonitoringService
from app.services.notification_service import NotificationService
from app.services.query_service import QueryService
from app.services.work_management_service import WorkManagementService
from app.workers.coordination_worker import CoordinationWorker


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        self.reads.append(key)
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _Upload:
    def __init__(self, content: bytes, filename: str = "evidence.txt") -> None:
        self.content = content
        self.filename = filename
        self.content_type = "text/plain"

    def read(self) -> bytes:
        return self.content


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _context(session: AsyncSession) -> tuple[User, User, Study, Site, Subject, VisitInstance, Query]:
    actor = User(
        email=f"phase2-actor-{uuid4()}@example.test",
        first_name="Phase",
        last_name="Two",
        status=UserStatus.active,
    )
    owner = User(
        email=f"phase2-owner-{uuid4()}@example.test",
        first_name="Work",
        last_name="Owner",
        status=UserStatus.active,
    )
    session.add_all([actor, owner])
    await session.flush()

    study = Study(study_code=f"PHASE2-{uuid4()}", title="Phase 2 qualification", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="001", name="Qualification site")
    session.add(site)
    await session.flush()
    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=uuid4(),
        subject_number="SUB-002",
        status=SubjectStatus.enrolled,
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()
    visit = VisitInstance(
        subject_id=subject.id,
        name="Week 4",
        visit_date=date(2026, 2, 1),
        window_status="in_window",
        status=VisitInstanceStatus.scheduled,
    )
    query = Query(
        study_id=study.id,
        site_id=site.id,
        subject_id=subject.id,
        target_type=QueryTargetType.subject.value,
        target_id=subject.id,
        text="EDC query text remains clinical authority",
        status=QueryStatus.open,
        created_by=actor.id,
    )
    session.add_all([visit, query])
    await session.flush()
    return actor, owner, study, site, subject, visit, query


def _scoped_ctms_user(user_id, study_id, site_id, *permissions):
    role = SimpleNamespace(
        role_permissions=[SimpleNamespace(permission=SimpleNamespace(code=permission)) for permission in permissions]
    )
    assignment = SimpleNamespace(role=role, study_id=study_id, site_id=site_id)
    return SimpleNamespace(id=user_id, status=UserStatus.active, user_roles=[assignment])


async def _published_plan(session, actor, study, site):
    service = MonitoringService()
    plan = await service.create_plan(
        session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        correlation_id="phase2-plan-create",
        payload={
            "name": "Qualification monitoring plan",
            "objectives": "Verify operational execution",
            "activity_types": [MonitoringActivityType.ROUTINE_MONITORING.value],
        },
    )
    published = await service.publish_plan(
        session, plan, actor_id=actor.id, correlation_id="phase2-plan-publish"
    )
    return service, plan, published


@pytest.mark.asyncio
async def test_phase2_monitoring_work_attachment_and_notification_boundary(db_session: AsyncSession):
    """Operational Phase 2 workflows compose without crossing EDC ownership."""

    actor, owner, study, site, subject, visit, query = await _context(db_session)
    monitoring, plan, published = await _published_plan(db_session, actor, study, site)

    with pytest.raises(ConflictError, match="immutable"):
        await monitoring.update_plan(db_session, plan, {"name": "tampered"}, actor_id=actor.id)

    draft = await monitoring.amend_plan(
        db_session,
        plan,
        {"cadence": "Every 4 weeks"},
        reason="Updated risk assessment",
        actor_id=actor.id,
    )
    versions = await monitoring.list_versions(db_session, plan)
    assert published.status == MonitoringPlanVersionStatus.PUBLISHED.value
    assert draft.version_number == 2
    assert [version.version_number for version in versions] == [1, 2]
    assert published.cadence is None

    db_session.add(
        FreezeLock(
            object_type="visit",
            object_id=visit.id,
            lock_type=FreezeLockType.freeze.value,
            is_active=True,
            locked_by=actor.id,
            locked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
    db_session.add(
        FreezeLock(
            object_type="visit",
            object_id=visit.id,
            lock_type=FreezeLockType.lock.value,
            is_active=True,
            locked_by=actor.id,
            locked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
    edc_snapshot = (visit.visit_date, visit.window_status, visit.status, subject.status, query.status, query.text)

    activity = await monitoring.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        correlation_id="phase2-activity-schedule",
        payload={
            "activity_type": MonitoringActivityType.ROUTINE_MONITORING.value,
            "planned_date": datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
            "assigned_cra_id": owner.id,
            "edc_visit_instance_id": visit.id,
        },
    )
    await monitoring.reschedule_activity(
        db_session, activity, datetime(2026, 3, 8, 10, 0, tzinfo=UTC),
        reason="Owner availability", actor_id=actor.id,
    )
    completed = await monitoring.complete_activity(
        db_session, activity, evidence="evidence://monitoring-report",
        notes="Completed while EDC visit remained locked", actor_id=owner.id,
    )
    assert completed.status == MonitoringActivityStatus.COMPLETED.value
    assert (visit.visit_date, visit.window_status, visit.status, subject.status, query.status, query.text) == edc_snapshot

    work = WorkManagementService()
    task = await work.create_query_follow_up(
        db_session,
        query_id=query.id,
        actor_id=actor.id,
        owner_id=owner.id,
        approved_summary="Review operational evidence only",
        correlation_id="phase2-query-follow-up",
    )
    contact = await work.create_contact(
        db_session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        name="Site coordinator",
        role="Coordinator",
        organization="Operations",
        owner_id=owner.id,
    )
    assert task.query_id == query.id
    assert task.query_summary == "Review operational evidence only"
    assert contact.study_id == study.id and contact.site_id == site.id
    assert query.status == QueryStatus.open and query.text == "EDC query text remains clinical authority"

    notifications = await NotificationService().list_ctms_for_scope(
        db_session, owner.id, study_id=study.id, site_id=site.id
    )
    notification_types = {notification.type for notification in notifications}
    assert {"ctms_monitoring_assigned", "ctms_task_assigned", "ctms_contact_assigned"} <= notification_types
    notification = notifications[0]
    assert notification.status == NotificationStatus.unread
    await NotificationService().mark_read(db_session, notification, owner.id)
    await NotificationService().archive(db_session, notification, owner.id)
    assert notification.status == NotificationStatus.archived

    storage = _MemoryStorage()
    attachments = FileAttachmentService(storage=storage)
    scoped_user = _scoped_ctms_user(
        owner.id, study.id, site.id, "ctms.operational-study-management", "ctms.operational-data-read"
    )
    operational = await attachments.upload_operational(
        db_session,
        parent_type="operational_task",
        parent_id=task.id,
        study_id=study.id,
        site_id=site.id,
        file=_Upload(b"operational evidence"),
        actor_id=owner.id,
        user=scoped_user,
        correlation_id="phase2-attachment",
    )
    assert await attachments.download(db_session, operational, scoped_user) == b"operational evidence"

    clinical = FileAttachment(
        module=Module.EDC.value,
        attachment_type="Clinical_Attachment",
        object_type=FileAttachmentObjectType.study.value,
        object_id=study.id,
        study_id=study.id,
        filename="clinical.pdf",
        content_type="application/pdf",
        size_bytes=7,
        storage_key="clinical/secret.pdf",
        uploaded_by=actor.id,
    )
    db_session.add(clinical)
    await db_session.flush()
    storage.objects[clinical.storage_key] = b"secret"
    with pytest.raises(AuthorizationError):
        await attachments.download(db_session, clinical, scoped_user)
    assert storage.reads == [operational.storage_key]


@pytest.mark.asyncio
async def test_phase2_projection_outbox_duplicate_and_stale_delivery(db_session: AsyncSession):
    """Allowlisted projections converge under duplicate and stale delivery."""

    _actor, _owner, study, site, subject, _visit, _query = await _context(db_session)
    service = CoordinationService()
    allowlist = {
        "subject_id": ProjectionFieldType.UUID.value,
        "status": ProjectionFieldType.STRING.value,
        "source_version": ProjectionFieldType.STRING.value,
    }

    async def accept(key: str, sequence: int, version: str, status: str):
        return await service.accept(
            db_session,
            event_type="SUBJECT_STATUS_PROJECTION",
            source_module=Module.EDC,
            target_module=Module.CTMS,
            entity_type="Subject",
            source_record_id=subject.id,
            source_version=version,
            source_sequence=sequence,
            source_timestamp=datetime(2026, 1, 1, 12, sequence, tzinfo=UTC),
            rule_version=1,
            payload={"subject_id": subject.id, "status": status, "source_version": version},
            allowlist=allowlist,
            idempotency_key=key,
            correlation_id=f"phase2-{key}",
            target_projection_type=ProjectionType.SUBJECT_STATUS.value,
            study_id=study.id,
            site_id=site.id,
        )

    first = await accept("event-1", 1, "1", "Screening")
    second = await accept("event-2", 2, "2", "Enrolled")
    results = await service.process_batch(db_session, [second, first], worker_id="phase2-worker")
    assert [result.event.event_id for result in results] == [first.event_id, second.event_id]
    assert [result.outcome for result in results] == ["succeeded", "succeeded"]
    await db_session.commit()

    duplicate = await service.process(db_session, event_id=second.event_id, worker_id="restarted-worker")
    assert duplicate.duplicate is True
    assert duplicate.resulting_projection_id == results[-1].resulting_projection_id
    assert await db_session.scalar(select(func.count(CoordinationEventLog.id))) == 2
    assert await db_session.scalar(select(func.count(CTMSOperationalProjection.id))) == 1

    stale = await accept("event-0", 0, "0", "Screen Failed")
    stale_result = await service.process(db_session, event_id=stale.event_id, worker_id="phase2-worker")
    assert stale_result.outcome == "conflict"
    projection = await db_session.scalar(select(CTMSOperationalProjection).where(CTMSOperationalProjection.source_record_id == subject.id))
    assert projection is not None
    assert projection.source_version == "2"
    assert projection.payload_json["status"] == "Enrolled"
    assert await db_session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == stale.event_id)) is not None

    projection_service = CTMSProjectionService()
    rejected = await projection_service.apply_projection(
        db_session,
        rule=StatusOwnershipRuleCreate(
            entity_type="Subject",
            field_path="status",
            authoritative_module=Module.EDC,
            writable_module=Module.EDC,
            projection_target=Module.CTMS,
            projection_type=ProjectionType.SUBJECT_STATUS,
            typed_allowlist={
                "status": ProjectionFieldType.STRING,
                "source_version": ProjectionFieldType.STRING,
            },
            version=1,
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        source_module=Module.EDC,
        source_record_id=uuid4(),
        payload={"status": "Completed", "clinical_data": "must not be retained"},
        source_version="3",
        source_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        correlation_id="phase2-rejected-projection",
    )
    assert rejected.rejected is True
    assert rejected.projection.payload_json == {}
    assert "must not be retained" not in repr(rejected.projection)


@pytest.mark.asyncio
async def test_phase2_transaction_rollback_removes_work_and_coordination_bookkeeping(db_session: AsyncSession):
    """Authoritative CTMS state, audit, status history, and outbox roll back together."""

    actor, owner, study, site, _subject, _visit, _query = await _context(db_session)
    work = WorkManagementService()
    task = await work.create_task(
        db_session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Atomic task",
        owner_id=owner.id,
        correlation_id="phase2-rollback-task",
    )
    assert task.id is not None
    await db_session.rollback()
    assert await db_session.scalar(select(func.count(AuditEvent.id))) == 0
    assert await db_session.scalar(select(func.count(CTMSStatusHistory.id))) == 0
    assert await db_session.scalar(select(func.count(CTMSOutbox.id))) == 0

    coordination = CoordinationService()
    event = await coordination.accept(
        db_session,
        event_type="SUBJECT_STATUS_PROJECTION",
        source_module=Module.EDC,
        target_module=Module.CTMS,
        entity_type="Subject",
        source_record_id=uuid4(),
        source_version="1",
        rule_version=1,
        payload={"status": "Enrolled"},
        idempotency_key="phase2-rollback-event",
        correlation_id="phase2-rollback-event",
        target_projection_type=ProjectionType.SUBJECT_STATUS.value,
    )
    await db_session.rollback()
    assert await db_session.scalar(select(CoordinationEvent).where(CoordinationEvent.event_id == event.event_id)) is None
    assert await db_session.scalar(select(func.count(CTMSOutbox.id))) == 0


@pytest.mark.asyncio
async def test_phase2_worker_outage_backpressure_and_edc_query_continue(db_session: AsyncSession):
    """Durable CTMS work remains pending while an EDC query still completes."""

    actor, _owner, study, site, subject, _visit, _query = await _context(db_session)
    queue = BoundedCoordinationQueue(capacity=1)
    coordination = CoordinationService(queue=queue)
    worker = CoordinationWorker(max_attempts=2)
    worker.queue = queue
    worker.unavailable()

    event = await coordination.accept(
        db_session,
        event_type="SUBJECT_STATUS_PROJECTION",
        source_module=Module.EDC,
        target_module=Module.CTMS,
        entity_type="Subject",
        source_record_id=subject.id,
        source_version="1",
        source_sequence=1,
        rule_version=1,
        payload={"status": "Enrolled"},
        idempotency_key="phase2-outage-event",
        correlation_id="phase2-outage-event",
        target_projection_type=ProjectionType.SUBJECT_STATUS.value,
        study_id=study.id,
        site_id=site.id,
    )
    await db_session.commit()
    assert queue.saturated
    assert await worker.claim_pending(db_session) == []
    durable = await db_session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))
    assert durable is not None and durable.status == "accepted"

    # The EDC workflow uses the same database while the CTMS worker is down;
    # no coordination delivery is required for a clinical query mutation.
    query = await QueryService().create_query(
        db_session,
        study_id=study.id,
        site_id=site.id,
        subject_id=subject.id,
        target_type=QueryTargetType.subject.value,
        target_id=subject.id,
        text="Clinical query remains available during CTMS outage",
        actor_id=actor.id,
    )
    assert query.status == QueryStatus.open
    await db_session.commit()

    worker.available()
    claimed = await worker.claim_pending(db_session)
    assert [row.event_id for row in claimed] == [event.event_id]
    assert queue.size <= queue.capacity
