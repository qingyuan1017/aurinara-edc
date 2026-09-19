"""Focused retention, restore, scope, and immutable-history tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CoordinationEventLog
from app.models.ctms.operational_study import OperationalStudy
from app.models.ctms.retention import CTMSRetentionAction
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.notification import Notification
from app.services.ctms_retention_service import CTMSRetentionService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _old(now: datetime) -> datetime:
    return now - timedelta(days=30)


def _study_record(now: datetime) -> OperationalStudy:
    return OperationalStudy(
        id=uuid4(),
        study_id=uuid4(),
        status="Closed",
        retention_state="active",
        created_by=uuid4(),
        updated_by=uuid4(),
        correlation_id=uuid4(),
        created_at=_old(now),
        updated_at=_old(now),
    )


@pytest.mark.asyncio
async def test_retention_cutoff_archives_old_ctms_data_but_not_recent_data_or_edc(db_session: AsyncSession):
    now = datetime(2026, 2, 1, tzinfo=UTC)
    service = CTMSRetentionService(settings=Settings(retention_days=7))
    old = _study_record(now)
    recent = _study_record(now)
    recent.created_at = now - timedelta(days=1)
    recent.updated_at = recent.created_at
    db_session.add_all([old, recent])
    await db_session.flush()

    result = await service.run(db_session, actor_id=uuid4(), reason="retention cutoff", now=now)

    assert result.archived >= 1
    assert old.retention_state == "archived"
    assert old.archived_at == now
    assert old.archived_by is not None
    assert old.retention_reason == "retention cutoff"
    assert recent.retention_state == "active"
    assert old.study_id != recent.study_id  # no EDC row is traversed or deleted
    assert await db_session.scalar(select(CTMSRetentionAction).where(CTMSRetentionAction.entity_id == old.id)) is not None


@pytest.mark.asyncio
async def test_restore_requires_actor_reason_and_keeps_restore_ledger(db_session: AsyncSession):
    now = datetime(2026, 2, 1, tzinfo=UTC)
    service = CTMSRetentionService(settings=Settings(retention_days=7))
    record = _study_record(now)
    db_session.add(record)
    await db_session.flush()
    await service.archive(db_session, record, actor_id=uuid4(), reason="study closed", now=now, resource="operational_study")

    with pytest.raises(Exception, match="reason"):
        await service.restore(db_session, record, actor_id=uuid4(), reason="", now=now)

    actor = uuid4()
    await service.restore(db_session, record, actor_id=actor, reason="approved reopening", now=now)
    assert record.retention_state == "active"
    actions = (await db_session.scalars(select(CTMSRetentionAction).where(CTMSRetentionAction.entity_id == record.id))).all()
    assert [item.action for item in actions] == ["retention_archive", "retention_restore"]
    assert actions[-1].actor_id == actor
    assert actions[-1].reason == "approved reopening"
    assert actions[-1].occurred_at.replace(tzinfo=UTC) == now


@pytest.mark.asyncio
async def test_shared_ctms_retention_scope_does_not_archive_edc_exports_or_notifications(db_session: AsyncSession):
    now = datetime(2026, 2, 1, tzinfo=UTC)
    old = _old(now)
    study_id = uuid4()
    ctms_export = Export(
        id=uuid4(), study_id=study_id, module="CTMS", content_owner="CTMS",
        export_type="json", status="Completed", requested_by=uuid4(), created_at=old,
    )
    edc_export = Export(
        id=uuid4(), study_id=study_id, module="EDC", content_owner="EDC",
        export_type="json", status="Completed", requested_by=uuid4(), created_at=old,
    )
    ctms_notification = Notification(
        id=uuid4(), user_id=uuid4(), module="CTMS", type="ctms_failed_event",
        payload_json={}, created_at=old,
    )
    edc_notification = Notification(
        id=uuid4(), user_id=uuid4(), module="EDC", type="query_assigned",
        payload_json={}, created_at=old,
    )
    db_session.add_all([ctms_export, edc_export, ctms_notification, edc_notification])
    await db_session.flush()

    await CTMSRetentionService(settings=Settings(retention_days=7)).run(
        db_session, actor_id=uuid4(), reason="resource cutoff", now=now
    )

    assert ctms_export.retention_state == "archived"
    assert ctms_notification.retention_state == "archived"
    assert edc_export.retention_state == "active"
    assert edc_notification.retention_state == "active"


@pytest.mark.asyncio
async def test_ctms_attachment_retention_records_soft_delete_actor_time_and_reason(db_session: AsyncSession):
    now = datetime(2026, 2, 1, tzinfo=UTC)
    actor = uuid4()
    attachment = FileAttachment(
        id=uuid4(),
        module="CTMS",
        attachment_type="Operational_Attachment",
        object_type="study",
        object_id=uuid4(),
        study_id=uuid4(),
        filename="monitoring-plan.pdf",
        content_type="application/pdf",
        size_bytes=12,
        storage_key="ctms/monitoring-plan.pdf",
        uploaded_by=uuid4(),
        uploaded_at=_old(now),
    )
    db_session.add(attachment)
    await db_session.flush()

    result = await CTMSRetentionService(settings=Settings(retention_days=7)).run(
        db_session, actor_id=actor, reason="attachment retention elapsed", now=now
    )

    assert result.soft_deleted >= 1
    assert attachment.deleted_at is not None
    assert attachment.deleted_by == actor
    assert attachment.delete_reason == "attachment retention elapsed"
    assert attachment.retention_state == "soft_deleted"


@pytest.mark.asyncio
async def test_completed_coordination_logs_and_audit_events_reject_update_and_delete(db_session: AsyncSession):
    completed = datetime(2025, 1, 1, tzinfo=UTC)
    log = CoordinationEventLog(
        id=uuid4(), event_id=uuid4(), source_module="CTMS", target_module="CTMS",
        entity_type="subject", source_record_id=uuid4(), rule_version=1,
        source_version="1", correlation_id="corr", outcome="succeeded", completed_at=completed,
    )
    audit = AuditEvent(
        id=uuid4(), actor_id=uuid4(), timestamp=completed, entity_type="operational_study",
        entity_id=uuid4(), module="CTMS", action="archive", request_id=uuid4(),
    )
    audit_id = audit.id
    db_session.add_all([log, audit])
    await db_session.commit()
    log_id = log.id

    log.sanitized_reason = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()

    audit = await db_session.scalar(select(AuditEvent).where(AuditEvent.id == audit_id))
    assert audit is not None
    audit.reason = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()

    log = await db_session.scalar(select(CoordinationEventLog).where(CoordinationEventLog.id == log_id))
    assert log is not None
    await db_session.delete(log)
    with pytest.raises(ValueError, match="cannot be deleted"):
        await db_session.flush()
