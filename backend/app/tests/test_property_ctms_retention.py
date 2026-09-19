"""Property 20: retention preserves CTMS history and immutable coordination records.

**Validates: Requirements 1.10, 3.10, 4.9, 5.14, 9.18, 12.4-12.5, 12.13**

The generated scenarios cover the configured CTMS archive/soft-delete policies,
retention cutoffs, and already-retained states.  All assertions use the real
retention service and SQLite persistence; no EDC rows are created or traversed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CoordinationEventLog
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.models.ctms.operational_study import OperationalStudy
from app.models.ctms.retention import CTMSRetentionAction
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.notification import Notification
from app.services.ctms_retention_service import CTMSRetentionService


@pytest.fixture
async def db_session() -> AsyncSession:
    """Provide an isolated database containing the complete model metadata."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@dataclass(frozen=True)
class RetentionCase:
    resource: str
    is_old: bool
    initial_state: str


@st.composite
def retention_cases(draw: st.DrawFn) -> RetentionCase:
    """Generate policy resources, cutoff positions, and existing states."""

    return RetentionCase(
        resource=draw(
            st.sampled_from(("operational_study", "attachment", "export", "notification", "projection"))
        ),
        is_old=draw(st.booleans()),
        initial_state=draw(st.sampled_from(("active", "archived", "soft_deleted"))),
    )


def _timestamp(now: datetime, is_old: bool) -> datetime:
    return now - timedelta(days=30 if is_old else 1)


def _record(case: RetentionCase, timestamp: datetime) -> object:
    """Create one persisted CTMS/shared record supported by the retention job."""

    actor = uuid4()
    study_id = uuid4()
    record_id = uuid4()
    common = {"retention_state": case.initial_state}
    if case.resource == "attachment":
        if case.initial_state == "archived":
            common.update(
                archived_at=timestamp,
                archived_by=actor,
                archive_reason="previous archive",
            )
        elif case.initial_state == "soft_deleted":
            common.update(
                deleted_at=timestamp,
                deleted_by=actor,
                delete_reason="previous deletion",
            )
    else:
        if case.initial_state == "archived":
            common.update(
                archived_at=timestamp,
                archived_by=actor,
                retention_reason="previous archive",
            )
        elif case.initial_state == "soft_deleted":
            common.update(
                deleted_at=timestamp,
                deleted_by=actor,
                deletion_reason="previous deletion",
            )

    if case.resource == "operational_study":
        return OperationalStudy(
            id=record_id,
            study_id=study_id,
            status="Closed",
            created_by=actor,
            updated_by=actor,
            correlation_id=uuid4(),
            created_at=timestamp,
            updated_at=timestamp,
            **common,
        )
    if case.resource == "attachment":
        return FileAttachment(
            id=record_id,
            module="CTMS",
            attachment_type="Operational_Attachment",
            object_type="operational",
            object_id=uuid4(),
            study_id=study_id,
            filename="generated-operational-record.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_key=f"ctms/{record_id}",
            uploaded_by=actor,
            uploaded_at=timestamp,
            **common,
        )
    if case.resource == "export":
        return Export(
            id=record_id,
            study_id=study_id,
            module="CTMS",
            content_owner="CTMS",
            export_type="json",
            status="Completed",
            requested_by=actor,
            created_at=timestamp,
            **common,
        )
    if case.resource == "notification":
        return Notification(
            id=record_id,
            user_id=actor,
            module="CTMS",
            type="ctms_retention_property",
            payload_json={"record_id": str(record_id)},
            created_at=timestamp,
            **common,
        )

    return CTMSOperationalProjection(
        id=record_id,
        projection_type="subject_status",
        source_module="EDC",
        source_record_id=uuid4(),
        study_id=study_id,
        source_version="1",
        source_timestamp=timestamp,
        projected_at=timestamp,
        rule_version=1,
        correlation_id=f"corr-{record_id}",
        payload_json={"status": "Enrolled"},
        payload_fingerprint="a" * 64,
        status=ProjectionStatus.CURRENT,
        **common,
    )


def _retained_snapshot(record: object) -> tuple[object, ...]:
    """Capture lifecycle fields before the retention run for skipped rows."""

    return tuple(
        getattr(record, field, None)
        for field in (
            "retention_state",
            "archived_at",
            "archived_by",
            "retention_reason",
            "deleted_at",
            "deleted_by",
            "deletion_reason",
        )
    )


@given(case=retention_cases())
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_retention_preserves_history_and_immutable_coordination_records(
    case: RetentionCase,
    db_session: AsyncSession,
) -> None:
    """Configured retention changes only eligible CTMS rows and keeps history."""

    now = datetime(2026, 2, 1, tzinfo=UTC)
    actor_id = uuid4()
    reason = f"generated retention reason for {case.resource}"
    record = _record(case, _timestamp(now, case.is_old))
    before = _retained_snapshot(record)
    db_session.add(record)
    await db_session.flush()
    record_id = record.id

    service = CTMSRetentionService(settings=Settings(retention_days=7))
    result = await service.run(db_session, actor_id=actor_id, reason=reason, now=now)

    eligible = case.initial_state == "active" and case.is_old
    if eligible:
        if case.resource == "attachment":
            assert result.soft_deleted >= 1
            assert record.retention_state == "soft_deleted"
            assert record.deleted_at == now
            assert record.deleted_by == actor_id
            assert record.delete_reason == reason
        else:
            assert result.archived >= 1
            assert record.retention_state == "archived"
            assert record.archived_at == now
            assert record.archived_by == actor_id
            assert record.retention_reason == reason

        actions = (
            await db_session.scalars(
                select(CTMSRetentionAction)
                .where(CTMSRetentionAction.entity_id == record_id)
                .order_by(CTMSRetentionAction.occurred_at)
            )
        ).all()
        assert actions
        assert actions[-1].actor_id == actor_id
        assert actions[-1].occurred_at.replace(tzinfo=UTC) == now
        assert actions[-1].reason == reason

        # Retention is logical: the same row and canonical reference remain
        # queryable after the state transition.
        queried = await db_session.get(type(record), record_id)
        assert queried is record
        assert queried.id == record_id
    else:
        assert _retained_snapshot(record) == before
        assert not (
            await db_session.scalars(
                select(CTMSRetentionAction).where(CTMSRetentionAction.entity_id == record_id)
            )
        ).all()

    # Completed coordination logs and CTMS audit events are protected history,
    # not retention candidates that can be changed or physically deleted.
    completed = datetime(2025, 1, 1, tzinfo=UTC)
    log = CoordinationEventLog(
        id=uuid4(),
        event_id=uuid4(),
        source_module="CTMS",
        target_module="CTMS",
        entity_type="subject",
        source_record_id=uuid4(),
        rule_version=1,
        source_version="1",
        correlation_id=f"immutable-{record_id}",
        outcome="succeeded",
        completed_at=completed,
    )
    audit = AuditEvent(
        id=uuid4(),
        actor_id=actor_id,
        timestamp=completed,
        entity_type="ctms_retention_property",
        entity_id=record_id,
        module="CTMS",
        action="retention_archive",
        request_id=uuid4(),
        correlation_id=f"immutable-{record_id}",
    )
    db_session.add_all([log, audit])
    log_id = log.id
    audit_id = audit.id
    await db_session.commit()

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
    await db_session.rollback()
