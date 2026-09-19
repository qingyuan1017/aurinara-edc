"""Focused tests for CTMS task 4.9 failure, retry, and conflict controls."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ServiceUnavailableError
from app.models.ctms.coordination import CTMSEventAttempt, CTMSOutbox
from app.models.ctms.retention import CTMSCoordinationConflict, CTMSFailedEvent
from app.services.coordination_service import CoordinationService, classify_failure


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _accept(service: CoordinationService, session: AsyncSession, *, key: str):
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
        target_projection_type="subject_status",
    )


def test_failure_classifier_retries_only_storage_and_service_failures():
    assert classify_failure(ServiceUnavailableError()).retryable
    assert classify_failure(TimeoutError()).code == "RETRYABLE_STORAGE_ERROR"
    assert not classify_failure("PROJECTION_FIELD_NOT_ALLOWED").retryable
    assert classify_failure("OWNERSHIP_VIOLATION").conflict
    assert classify_failure("AMBIGUOUS_REFERENCE").code == "AMBIGUOUS_REFERENCE"


@pytest.mark.asyncio
async def test_unknown_reference_creates_sanitized_failed_event(db_session: AsyncSession):
    class MissingResolver:
        async def resolve(self, *_args, **_kwargs):
            return None

    service = CoordinationService(identity_resolver=MissingResolver())
    event = await _accept(service, db_session, key="unknown-reference")
    result = await service.process(db_session, event_id=event.event_id, worker_id="worker")

    assert result.outcome == "failed"
    failed = await db_session.scalar(
        select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id)
    )
    assert failed is not None
    assert failed.reason_code == "RECORD_NOT_FOUND"
    assert "payload" not in str(failed.sanitized_details_json).lower()


@pytest.mark.asyncio
async def test_retryable_failure_is_bounded_and_scheduled(db_session: AsyncSession):
    service = CoordinationService()
    event = await _accept(service, db_session, key="retryable-storage")
    service._apply_target = AsyncMock(side_effect=ServiceUnavailableError())

    before = datetime.now(UTC)
    result = await service.process(db_session, event_id=event.event_id, worker_id="worker")
    assert result.outcome == "retrying"
    assert event.status == "retrying"
    assert event.sanitized_reason == "RETRYABLE_STORAGE_ERROR"
    assert event.attempt_count == 1
    attempts = (await db_session.scalars(select(CTMSEventAttempt))).all()
    assert len(attempts) == 1
    assert attempts[0].sanitized_detail == "RETRYABLE_STORAGE_ERROR"
    outbox = await db_session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))
    assert outbox is not None
    assert outbox.available_at > before
    assert await db_session.scalar(
        select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id)
    ) is None


@pytest.mark.asyncio
async def test_ownership_conflict_creates_dedicated_conflict_record(db_session: AsyncSession):
    service = CoordinationService()
    event = await service.accept(
        db_session,
        event_type="COORDINATED_TRANSITION",
        source_module="CTMS",
        target_module="EDC",
        entity_type="Subject",
        source_record_id=uuid4(),
        source_version="1",
        rule_version=1,
        payload={"status": "active"},
        idempotency_key="ownership-conflict",
        correlation_id="correlation-ownership-conflict",
        target_projection_type="coordinated_transition",
    )
    result = await service.process(db_session, event_id=event.event_id, worker_id="worker")

    assert result.outcome == "conflict"
    conflict = await db_session.scalar(
        select(CTMSCoordinationConflict).where(CTMSCoordinationConflict.event_id == event.event_id)
    )
    assert conflict is not None
    assert conflict.conflict_type == "PROJECTION_TARGET_NOT_CTMS"
    assert conflict.status == "open"
    assert "payload" not in str(conflict.sanitized_details_json).lower()
