"""Property-based verification of idempotent CTMS coordination delivery.

# Feature: ctms-integration, Property 11: Coordination is idempotent

**Validates: Requirements 1.7, 4.11, 9.2-9.8, 9.18**

The property uses the real coordination service and CTMS projection persistence
against SQLite.  Each generated scenario runs inside a savepoint so Hypothesis
can exercise independent accepted events without sharing durable state between
examples.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.ctms.coordination import (
    CoordinationEventStatus,
    CTMSCoordinationEvent,
    CTMSCoordinationEventLog,
    CTMSEventAttempt,
    CTMSOutbox,
)
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.services.coordination_service import CoordinationService


@pytest.fixture
async def db_session() -> AsyncSession:
    """Provide the coordination tables for the generated database scenarios."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@dataclass(frozen=True)
class CoordinationCase:
    """Generated event metadata and an at-least-twice delivery sequence."""

    idempotency_key: str
    source_record_id: UUID
    source_version: str
    source_sequence: int
    status: str
    workers: tuple[str, ...]
    target_projection_type: str


@st.composite
def coordination_cases(draw: st.DrawFn) -> CoordinationCase:
    """Generate safe accepted events, projection payloads, and duplicate deliveries."""

    return CoordinationCase(
        idempotency_key=draw(st.from_regex(r"idem-[a-z0-9]{1,16}", fullmatch=True)),
        source_record_id=draw(st.uuids(version=4)),
        source_version=str(draw(st.integers(min_value=1, max_value=1000))),
        source_sequence=draw(st.integers(min_value=0, max_value=1000)),
        status=draw(st.sampled_from(("Screening", "Enrolled", "Completed", "Withdrawn"))),
        workers=tuple(
            draw(
                st.lists(
                    st.from_regex(r"worker-[a-z0-9]{1,8}", fullmatch=True),
                    min_size=2,
                    max_size=6,
                )
            )
        ),
        target_projection_type=draw(st.just("subject_status")),
    )


async def _accept(
    service: CoordinationService,
    session: AsyncSession,
    case: CoordinationCase,
) -> CTMSCoordinationEvent:
    return await service.accept(
        session,
        event_type="SUBJECT_STATUS_PROJECTION",
        source_module="EDC",
        target_module="CTMS",
        entity_type="Subject",
        source_record_id=case.source_record_id,
        source_version=case.source_version,
        rule_version=1,
        source_sequence=case.source_sequence,
        payload={
            "subject_id": str(case.source_record_id),
            "status": case.status,
            "source_version": case.source_version,
        },
        idempotency_key=case.idempotency_key,
        correlation_id=f"corr-{case.idempotency_key}",
        target_projection_type=case.target_projection_type,
    )


@given(case=coordination_cases())
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_coordination_is_idempotent_for_duplicate_delivery(
    case: CoordinationCase,
    db_session: AsyncSession,
) -> None:
    """Duplicate acceptance and delivery produce one logical update and outcome."""

    service = CoordinationService()
    nested = await db_session.begin_nested()
    try:
        first = await _accept(service, db_session, case)
        accepted_events = [first]
        accepted_events.extend(
            [await _accept(service, db_session, case) for _ in case.workers[1:]]
        )

        # Idempotency is enforced at admission as well as processing: every
        # duplicate delivery resolves to the same immutable event identity.
        assert {event.event_id for event in accepted_events} == {first.event_id}
        assert await db_session.scalar(
            select(func.count(CTMSCoordinationEvent.id)).where(
                CTMSCoordinationEvent.source_module == "EDC",
                CTMSCoordinationEvent.idempotency_key == case.idempotency_key,
            )
        ) == 1
        assert await db_session.scalar(
            select(func.count(CTMSOutbox.id)).where(CTMSOutbox.event_id == first.event_id)
        ) == 1

        results = [
            await service.process(db_session, event_id=first.event_id, worker_id=worker)
            for worker in case.workers
        ]

        first_result = results[0]
        assert first_result.outcome == CoordinationEventStatus.SUCCEEDED.value
        assert first_result.resulting_projection_id is not None
        assert all(result.outcome == first_result.outcome for result in results)
        assert all(
            result.resulting_projection_id == first_result.resulting_projection_id
            for result in results
        )
        assert results[0].duplicate is False
        assert all(result.duplicate is True for result in results[1:])

        # A duplicate delivery returns the completed result rather than adding
        # another worker attempt, log, outbox row, or projection row.
        assert await db_session.scalar(
            select(func.count(CTMSEventAttempt.id)).where(
                CTMSEventAttempt.event_id == first.event_id
            )
        ) == 1
        assert await db_session.scalar(
            select(func.count(CTMSCoordinationEventLog.id)).where(
                CTMSCoordinationEventLog.event_id == first.event_id
            )
        ) == 1
        assert await db_session.scalar(
            select(func.count(CTMSOperationalProjection.id)).where(
                CTMSOperationalProjection.projection_type == case.target_projection_type,
                CTMSOperationalProjection.source_module == "EDC",
                CTMSOperationalProjection.source_record_id == case.source_record_id,
            )
        ) == 1

        projection = await db_session.scalar(
            select(CTMSOperationalProjection).where(
                CTMSOperationalProjection.id == first_result.resulting_projection_id
            )
        )
        assert projection is not None
        assert projection.status == ProjectionStatus.CURRENT
        assert projection.payload_json["status"] == case.status
        assert first.status == CoordinationEventStatus.SUCCEEDED.value
    finally:
        await nested.rollback()
