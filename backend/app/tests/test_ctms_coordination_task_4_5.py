"""Focused persistence and transaction tests for CTMS task 4.5."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.audit import AuditEvent
from app.models.ctms.coordination import (
    CoordinationEventLog,
    CoordinationEventStatus,
    CTMSCoordinationEvent,
    CTMSOutbox,
)
from app.models.ctms.projection import CTMSOperationalProjection
from app.services.coordination_service import CoordinationService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _accept(service: CoordinationService, session: AsyncSession, *, key: str, target_type: str | None = "subject_status"):
    source_id = uuid4()
    return await service.accept(
        session,
        event_type="SUBJECT_STATUS_PROJECTION",
        source_module="EDC",
        target_module="CTMS",
        entity_type="Subject",
        source_record_id=source_id,
        source_version="1",
        rule_version=1,
        source_sequence=1,
        payload={"subject_id": str(source_id), "status": "Enrolled", "source_version": "1"},
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        target_projection_type=target_type,
    )


@pytest.mark.asyncio
async def test_acceptance_rolls_back_event_outbox_and_audit_together(db_session: AsyncSession):
    service = CoordinationService()
    event = await _accept(service, db_session, key="atomic-1")
    assert event.status == CoordinationEventStatus.ACCEPTED.value
    assert await db_session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id)) is not None
    await db_session.rollback()

    assert await db_session.scalar(select(CTMSCoordinationEvent).where(CTMSCoordinationEvent.event_id == event.event_id)) is None
    assert await db_session.scalar(select(func.count(CTMSOutbox.id))) == 0
    assert await db_session.scalar(select(func.count(AuditEvent.id))) == 0


@pytest.mark.asyncio
async def test_duplicate_idempotency_returns_one_event_and_one_processing_outcome(db_session: AsyncSession):
    service = CoordinationService()
    first = await _accept(service, db_session, key="duplicate-1")
    duplicate = await _accept(service, db_session, key="duplicate-1")
    assert duplicate.event_id == first.event_id
    assert await db_session.scalar(select(func.count(CTMSCoordinationEvent.id))) == 1
    assert await db_session.scalar(select(func.count(CTMSOutbox.id))) == 1

    first_result = await service.process(db_session, event_id=first.event_id, worker_id="worker-1")
    second_result = await service.process(db_session, event_id=first.event_id, worker_id="worker-2")
    assert first_result.outcome == "succeeded"
    assert second_result.outcome == first_result.outcome
    assert second_result.resulting_projection_id == first_result.resulting_projection_id
    assert second_result.duplicate is True
    assert await db_session.scalar(select(func.count(CoordinationEventLog.id))) == 1
    assert await db_session.scalar(select(func.count(CTMSOperationalProjection.id))) == 1


@pytest.mark.asyncio
async def test_completed_event_log_is_immutable_at_application_layer(db_session: AsyncSession):
    service = CoordinationService()
    event = await _accept(service, db_session, key="immutable-1")
    event_id = event.event_id
    await service.process(db_session, event_id=event_id, worker_id="worker-1")
    await db_session.commit()

    log = await db_session.scalar(select(CoordinationEventLog).where(CoordinationEventLog.event_id == event_id))
    assert log is not None
    log.sanitized_reason = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()

    log = await db_session.scalar(select(CoordinationEventLog).where(CoordinationEventLog.event_id == event_id))
    assert log is not None
    await db_session.delete(log)
    with pytest.raises(ValueError, match="cannot be deleted"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_processing_does_not_update_unnamed_or_non_ctms_targets(db_session: AsyncSession):
    service = CoordinationService()
    unnamed = await _accept(service, db_session, key="target-unnamed", target_type=None)
    unnamed.target_record_id = uuid4()
    unnamed_result = await service.process(db_session, event_id=unnamed.event_id, worker_id="worker-1")
    assert unnamed_result.outcome == "conflict"
    assert unnamed_result.resulting_projection_id is None

    non_ctms = await service.accept(
        db_session,
        event_type="COORDINATED_TRANSITION",
        source_module="CTMS",
        target_module="EDC",
        entity_type="subject_status",
        source_record_id=uuid4(),
        source_version="1",
        rule_version=1,
        payload={"status": "active"},
        idempotency_key="target-edc-1",
        correlation_id="correlation-target-edc-1",
        target_projection_type="coordinated_transition",
    )
    result = await service.process(db_session, event_id=non_ctms.event_id, worker_id="worker-1")
    assert result.outcome == "conflict"
    assert await db_session.scalar(select(func.count(CTMSOperationalProjection.id))) == 0


@pytest.mark.asyncio
async def test_target_and_target_audit_roll_back_as_one_transaction(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    service = CoordinationService()
    event = await _accept(service, db_session, key="target-atomic-1")
    await db_session.commit()

    monkeypatch.setattr("app.services.ctms_projection_service.audit_service.record", AsyncMock(side_effect=RuntimeError("audit unavailable")))
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.process(db_session, event_id=event.event_id, worker_id="worker-1")
    await db_session.rollback()

    assert await db_session.scalar(select(func.count(CTMSOperationalProjection.id))) == 0
    assert await db_session.scalar(select(func.count(CoordinationEventLog.id))) == 0
