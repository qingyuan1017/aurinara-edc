"""Async database-boundary tests for CTMS coordination task 4.14."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.ctms import Module
from app.core.database import Base
from app.core.exceptions import ServiceUnavailableError
from app.models.audit import AuditEvent
from app.models.ctms.coordination import (
    CoordinationEvent,
    CoordinationEventLog,
    CTMSEventAttempt,
    CTMSOutbox,
)
from app.models.ctms.ownership import ProjectionType
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.retention import CTMSCoordinationConflict, CTMSFailedEvent
from app.schemas.ctms.coordination import ConflictResolveRequest
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.coordination_service import CoordinationService
from app.services.ctms_projection_service import CTMSProjectionService
from app.workers.coordination_worker import CoordinationWorker
from app.workers.projection_rebuild_worker import (
    AuthoritativeRecordSnapshot,
    ProjectionRebuildWorker,
)


class DatabaseHarness:
    def __init__(self, factory: async_sessionmaker[AsyncSession], engine) -> None:
        self.factory = factory
        self.engine = engine


@pytest.fixture
async def database() -> DatabaseHarness:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield DatabaseHarness(factory, engine)
    await engine.dispose()


def _payload(source_id, status: str = "Enrolled") -> dict[str, str]:
    return {"subject_id": str(source_id), "status": status, "source_version": "1"}


async def _accept(
    service: CoordinationService,
    session: AsyncSession,
    *,
    key: str,
    source_id=None,
    source_sequence: int | None = 1,
    source_version: str | int = "1",
    payload: dict | None = None,
    target_type: str | None = "subject_status",
    source_module: str = "EDC",
    target_module: str = "CTMS",
    study_id=None,
):
    source_id = source_id or uuid4()
    return await service.accept(
        session,
        event_type="SUBJECT_STATUS_PROJECTION",
        source_module=source_module,
        target_module=target_module,
        entity_type="Subject",
        source_record_id=source_id,
        source_version=source_version,
        rule_version=1,
        source_sequence=source_sequence,
        source_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        payload=payload or _payload(source_id),
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        target_projection_type=target_type,
        study_id=study_id,
    )


def _subject_rule() -> StatusOwnershipRuleCreate:
    return StatusOwnershipRuleCreate(
        entity_type="Subject",
        field_path="status",
        authoritative_module=Module.EDC,
        writable_module=Module.EDC,
        projection_target=Module.CTMS,
        projection_type=ProjectionType.SUBJECT_STATUS,
        typed_allowlist={
            "subject_id": ProjectionFieldType.UUID,
            "approved_reference": ProjectionFieldType.STRING,
            "status": ProjectionFieldType.STRING,
            "source_version": ProjectionFieldType.STRING,
        },
        version=4,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_acceptance_rolls_back_authoritative_event_outbox_and_audit(database):
    service = CoordinationService()
    async with database.factory() as session:
        event = await _accept(service, session, key="atomic-boundary")
        assert await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))
        await session.rollback()

    async with database.factory() as session:
        assert await session.scalar(select(CoordinationEvent).where(CoordinationEvent.event_id == event.event_id)) is None
        assert await session.scalar(select(func.count(CTMSOutbox.id))) == 0
        assert await session.scalar(select(func.count(AuditEvent.id))) == 0


@pytest.mark.asyncio
async def test_duplicate_delivery_after_worker_restart_has_one_side_effect(database):
    service = CoordinationService()
    async with database.factory() as session:
        event = await _accept(service, session, key="restart-duplicate")
        await session.commit()

    async with database.factory() as first_worker_session:
        first = await service.process(first_worker_session, event_id=event.event_id, worker_id="worker-a")
        assert first.outcome == "succeeded", first.reason
        await first_worker_session.commit()

    async with database.factory() as restarted_worker_session:
        second = await service.process(restarted_worker_session, event_id=event.event_id, worker_id="worker-b")
        assert second.duplicate is True
        assert second.outcome == first.outcome
        assert second.resulting_projection_id == first.resulting_projection_id
        assert await restarted_worker_session.scalar(select(func.count(CoordinationEventLog.id))) == 1
        assert await restarted_worker_session.scalar(select(func.count(CTMSOperationalProjection.id))) == 1


@pytest.mark.asyncio
async def test_completed_event_log_cannot_be_mutated_or_deleted_after_restart(database):
    service = CoordinationService()
    async with database.factory() as session:
        event = await _accept(service, session, key="immutable-boundary")
        await service.process(session, event_id=event.event_id, worker_id="worker-a")
        await session.commit()

    async with database.factory() as session:
        log = await session.scalar(select(CoordinationEventLog).where(CoordinationEventLog.event_id == event.event_id))
        assert log is not None
        log.outcome = "tampered"
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()

        log = await session.scalar(select(CoordinationEventLog).where(CoordinationEventLog.event_id == event.event_id))
        await session.delete(log)
        with pytest.raises(ValueError, match="cannot be deleted"):
            await session.flush()


@pytest.mark.asyncio
async def test_worker_batch_applies_source_order_and_stale_delivery_preserves_current_projection(database):
    service = CoordinationService()
    source_id = uuid4()
    async with database.factory() as session:
        older = await _accept(
            service, session, key="ordered-1", source_id=source_id, source_sequence=1,
            source_version="1", payload=_payload(source_id, "Screening"),
        )
        newer = await _accept(
            service, session, key="ordered-2", source_id=source_id, source_sequence=2,
            source_version="2", payload={**_payload(source_id, "Enrolled"), "source_version": "2"},
        )
        results = await service.process_batch(session, [newer, older], worker_id="ordered-worker")
        assert [result.event.event_id for result in results] == [older.event_id, newer.event_id]
        assert [result.outcome for result in results] == ["succeeded", "succeeded"]
        projection = await session.scalar(select(CTMSOperationalProjection).where(
            CTMSOperationalProjection.source_record_id == source_id,
        ))
        assert projection is not None
        assert projection.source_sequence == 2
        assert projection.payload_json["status"] == "Enrolled"

        stale = await _accept(
            service, session, key="ordered-stale", source_id=source_id, source_sequence=0,
            source_version="0", payload=_payload(source_id, "Screen Failed"),
        )
        stale_result = await service.process(session, event_id=stale.event_id, worker_id="ordered-worker")
        assert stale_result.outcome == "conflict"
        conflict = await session.scalar(select(CTMSCoordinationConflict).where(
            CTMSCoordinationConflict.event_id == stale.event_id,
        ))
        assert conflict is not None
        assert conflict.conflict_type == "OUT_OF_ORDER_EVENT"


@pytest.mark.asyncio
async def test_retry_exhaustion_creates_failed_event_without_target_mutation(database, monkeypatch):
    service = CoordinationService()
    service._apply_target = AsyncMock(side_effect=ServiceUnavailableError())
    monkeypatch.setattr(
        "app.services.coordination_service.get_settings",
        lambda: SimpleNamespace(
            ctms_coordination_max_attempts=2,
            ctms_coordination_backoff_base_seconds=1,
            ctms_coordination_backoff_max_seconds=2,
        ),
    )
    async with database.factory() as session:
        event = await _accept(service, session, key="retry-exhaustion")
        assert (await service.process(session, event_id=event.event_id, worker_id="worker-a")).outcome == "retrying"
        result = await service.process(session, event_id=event.event_id, worker_id="worker-b")
        assert result.outcome == "failed"
        failed = await session.scalar(select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id))
        assert failed is not None
        assert failed.reason_code == "RETRY_LIMIT_EXCEEDED"
        assert await session.scalar(select(func.count(CTMSOperationalProjection.id))) == 0
        attempts = (await session.scalars(select(CTMSEventAttempt).where(CTMSEventAttempt.event_id == event.event_id))).all()
        assert [attempt.outcome for attempt in attempts] == ["retrying", "failed"]


@pytest.mark.asyncio
async def test_failure_records_retain_only_sanitized_reason_codes(database):
    service = CoordinationService()
    service._apply_target = AsyncMock(side_effect=RuntimeError("database password and raw payload leaked"))
    async with database.factory() as session:
        event = await _accept(service, session, key="sanitized-failure")
        result = await service.process(session, event_id=event.event_id, worker_id="worker")
        assert result.outcome == "failed"
        failed = await session.scalar(select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id))
        assert failed is not None
        serialized = str(failed.sanitized_details_json).lower()
        assert "password" not in serialized
        assert "payload" not in serialized
        assert failed.sanitized_details_json == {"reason_code": "SCHEMA_VALIDATION_FAILED"}


@pytest.mark.asyncio
async def test_conflict_resolution_requeues_only_the_selected_event(database):
    service = CoordinationService()
    async with database.factory() as session:
        event = await _accept(
            service, session, key="resolve-conflict", source_module="CTMS", target_module="EDC",
            target_type="coordinated_transition",
        )
        assert (await service.process(session, event_id=event.event_id, worker_id="worker")).outcome == "conflict"
        conflict = await session.scalar(select(CTMSCoordinationConflict).where(
            CTMSCoordinationConflict.event_id == event.event_id,
        ))
        assert conflict is not None
        outbox = await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))
        assert outbox is not None

        from app.api.routes.ctms.coordination import resolve_coordination_conflict

        response = await resolve_coordination_conflict(
            conflict.id,
            ConflictResolveRequest(policy="apply_source", reason="Ownership policy was reviewed"),
            session,
            SimpleNamespace(id=uuid4()),
        )
        assert response.status == "resolved"
        assert response.policy == "apply_source"
        assert conflict.sanitized_details_json == {"reason_code": "RESOLVED", "policy": "apply_source"}
        assert outbox.status == "Pending"
        assert outbox.outcome is None


@pytest.mark.asyncio
async def test_replay_revalidates_identity_before_requeue_and_then_can_resume(database):
    class Resolver:
        available = False

        async def resolve(self, *_args, **_kwargs):
            return object() if self.available else None

    resolver = Resolver()
    service = CoordinationService(identity_resolver=resolver)
    async with database.factory() as session:
        event = await _accept(service, session, key="replay-policy")
        assert (await service.process(session, event_id=event.event_id, worker_id="worker")).outcome == "failed"
        actor = SimpleNamespace(id=uuid4())
        with pytest.raises(Exception, match="not found"):
            await service.replay_failed_event(session, event_id=event.event_id, actor=actor, reason="retry after review")
        assert event.status == "failed"

        resolver.available = True
        outbox = await service.replay_failed_event(
            session, event_id=event.event_id, actor=actor, reason="canonical identity restored"
        )
        assert outbox.status == "Pending"
        assert event.status == "accepted"
        assert event.attempt_count == 0
        failed = await session.scalar(select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id))
        assert failed is not None
        assert failed.sanitized_details_json == {"reason_code": "REPLAY_PENDING"}


@pytest.mark.asyncio
async def test_worker_outage_leaves_accepted_outbox_durable_until_restart(database):
    service = CoordinationService()
    worker = CoordinationWorker(max_attempts=2)
    worker_service_queue = service.queue
    worker.queue = worker_service_queue
    async with database.factory() as session:
        event = await _accept(service, session, key="worker-outage")
        await session.commit()

    worker.unavailable()
    async with database.factory() as session:
        assert await worker.claim_pending(session) == []
        durable = await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))
        assert durable is not None
        assert durable.status == "accepted"

    worker.available()
    async with database.factory() as session:
        claimed = await worker.claim_pending(session)
        assert [row.event_id for row in claimed] == [event.event_id]
        await session.rollback()


class _DatabaseSourceReader:
    def __init__(self, records: list[AuthoritativeRecordSnapshot]) -> None:
        self.records = records

    async def list_records(self, session, **_kwargs):
        return list(reversed(self.records))


@pytest.mark.asyncio
async def test_projection_rebuild_is_repeatable_source_preserving_and_does_not_enqueue(database):
    study_id, site_id = uuid4(), uuid4()
    source_id = uuid4()
    records = [
        AuthoritativeRecordSnapshot(
            source_record_id=source_id,
            source_module=Module.EDC,
            source_version="2",
            source_timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            study_id=study_id,
            site_id=site_id,
            subject_id=source_id,
            payload={
                "subject_id": str(source_id),
                "approved_reference": "SUB-001",
                "status": "Enrolled",
                "source_version": "2",
            },
        )
    ]
    source_snapshot = [(record.source_version, dict(record.payload)) for record in records]
    worker = ProjectionRebuildWorker(
        source_reader=_DatabaseSourceReader(records),
        projection_service=CTMSProjectionService(),
    )
    async with database.factory() as session:
        first = await worker.rebuild(
            session,
            study_id=study_id,
            site_id=site_id,
            projection_type=ProjectionType.SUBJECT_STATUS,
            source_module=Module.EDC,
            rule=_subject_rule(),
            generation=uuid4(),
            correlation_id="rebuild-one",
        )
        first_values = [
            (row.payload_json, row.payload_fingerprint, row.source_version)
            for row in first.projections
        ]
        second = await worker.rebuild(
            session,
            study_id=study_id,
            site_id=site_id,
            projection_type=ProjectionType.SUBJECT_STATUS,
            source_module=Module.EDC,
            rule=_subject_rule(),
            generation=uuid4(),
            correlation_id="rebuild-two",
        )
        second_values = [
            (row.payload_json, row.payload_fingerprint, row.source_version)
            for row in second.projections
        ]
        assert second_values == first_values
        assert records[0].source_version == source_snapshot[0][0]
        assert dict(records[0].payload) == source_snapshot[0][1]
        assert await session.scalar(select(func.count(CTMSOutbox.id))) == 0
        assert await session.scalar(select(func.count(CTMSOperationalProjection.id))) == 1
        assert first.state.generation != second.state.generation
