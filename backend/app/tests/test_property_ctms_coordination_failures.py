"""Property 13: Coordination failures are bounded and sanitized.

**Validates: Requirements 9.10-9.15, 13.13-13.15**

The generated worker sequences exercise retryable service failures, terminal
validation failures, ownership conflicts, and successful application.  The
real coordination service and SQLite persistence are used so each assertion
covers the durable event, attempts, outbox, retained remediation record, and
projection boundary rather than a standalone classifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ServiceUnavailableError, ValidationError
from app.models.ctms.coordination import (
    CTMSCoordinationEventLog,
    CTMSEventAttempt,
    CTMSOutbox,
)
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.retention import CTMSCoordinationConflict, CTMSFailedEvent
from app.services.coordination_service import CoordinationService

WorkerResult = Literal["retryable", "failed", "conflict", "success"]


@pytest.fixture
async def db_session() -> AsyncSession:
    """Provide isolated coordination persistence for each generated example."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@dataclass(frozen=True)
class FailureCase:
    """A retry policy and a worker sequence that always reaches a terminal state."""

    max_attempts: int
    worker_results: tuple[WorkerResult, ...]
    prohibited_value: str


@st.composite
def failure_cases(draw: st.DrawFn) -> FailureCase:
    """Generate bounded retry sequences followed by success or terminal failure."""

    max_attempts = draw(st.integers(min_value=1, max_value=5))
    prohibited_value = draw(
        st.sampled_from(
            (
                "password=do-not-retain",
                "Clinical_Data=subject-value",
                "raw event payload with unrestricted query message",
                "postgresql://credentials@example.test/edc",
            )
        )
    )
    retry_prefix = draw(
        st.lists(
            st.just("retryable"),
            min_size=0,
            max_size=max_attempts - 1,
        )
    )
    if draw(st.booleans()):
        # Exhaustion must require exactly the configured number of attempts.
        worker_results: tuple[WorkerResult, ...] = ("retryable",) * max_attempts
    else:
        worker_results = (*retry_prefix, draw(st.sampled_from(("success", "failed", "conflict"))))
    return FailureCase(max_attempts, worker_results, prohibited_value)


class SequencedCoordinationService(CoordinationService):
    """Inject generated worker outcomes while retaining production processing."""

    def __init__(self, worker_results: tuple[WorkerResult, ...]) -> None:
        super().__init__()
        self.worker_results = list(worker_results)

    async def _apply_target(self, session, event, *, worker_id: str):
        result = self.worker_results.pop(0)
        if result == "retryable":
            raise ServiceUnavailableError(
                "worker failed with sensitive details",
                {"reason": "SERVICE_UNAVAILABLE", "payload": "not retained"},
            )
        if result == "failed":
            raise ValidationError(
                "validation failed with sensitive details",
                {"reason": "SCHEMA_VALIDATION_FAILED", "payload": "not retained"},
            )
        if result == "conflict":
            raise ConflictError(
                "ownership conflict with sensitive details",
                {"reason": "OWNERSHIP_VIOLATION", "payload": "not retained"},
            )
        return await super()._apply_target(session, event, worker_id=worker_id)


async def _accept(service: CoordinationService, session: AsyncSession) -> object:
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
        payload={
            "subject_id": str(source_id),
            "status": "Enrolled",
            "source_version": "1",
        },
        idempotency_key=f"property-13-{uuid4()}",
        correlation_id=f"property-13-{uuid4()}",
        target_projection_type="subject_status",
    )


@given(case=failure_cases())
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_coordination_failures_are_bounded_and_sanitized(
    case: FailureCase,
    db_session: AsyncSession,
) -> None:
    """Retryable failures are bounded and terminal outcomes retain no payload data.

    **Validates: Requirements 9.10-9.15, 13.13-13.15**
    """

    service = SequencedCoordinationService(case.worker_results)
    event = await _accept(service, db_session)
    settings = SimpleNamespace(
        ctms_coordination_max_attempts=case.max_attempts,
        ctms_coordination_backoff_base_seconds=1,
        ctms_coordination_backoff_max_seconds=60,
    )

    # The service imports get_settings locally, so patching its module binding
    # keeps this generated policy scoped to one example.
    from unittest.mock import patch

    with patch("app.services.coordination_service.get_settings", return_value=settings):
        results = []
        while True:
            result = await service.process(
                db_session,
                event_id=event.event_id,
                worker_id="property-13-worker",
            )
            results.append(result)
            if result.outcome != "retrying":
                break

    assert len(results) <= case.max_attempts
    assert event.attempt_count == len(results)
    assert len(service.worker_results) == 0
    attempts = list(
        (
            await db_session.scalars(
                select(CTMSEventAttempt)
                .where(CTMSEventAttempt.event_id == event.event_id)
                .order_by(CTMSEventAttempt.attempt_number)
            )
        ).all()
    )
    assert len(attempts) == len(results)
    assert all(attempt.sanitized_detail != case.prohibited_value for attempt in attempts)

    final = results[-1]
    projection_count = await db_session.scalar(
        select(func.count(CTMSOperationalProjection.id)).where(
            CTMSOperationalProjection.source_record_id == event.source_record_id
        )
    )
    failed = await db_session.scalar(
        select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id)
    )
    conflict = await db_session.scalar(
        select(CTMSCoordinationConflict).where(CTMSCoordinationConflict.event_id == event.event_id)
    )

    terminal_worker_result = case.worker_results[len(results) - 1]
    if terminal_worker_result == "success":
        assert final.outcome == "succeeded"
        assert event.sanitized_reason is None
        assert projection_count == 1
        assert failed is None
        assert conflict is None
    elif terminal_worker_result == "conflict":
        assert final.outcome == "conflict"
        assert final.reason == "OWNERSHIP_VIOLATION"
        assert projection_count == 0
        assert failed is None
        assert conflict is not None
    else:
        assert final.outcome == "failed"
        expected_reason = (
            "RETRY_LIMIT_EXCEEDED"
            if terminal_worker_result == "retryable"
            else "SCHEMA_VALIDATION_FAILED"
        )
        assert final.reason == expected_reason
        assert projection_count == 0
        assert failed is not None
        assert conflict is None

    retained_rows = [event.sanitized_reason or ""]
    retained_rows.extend(attempt.sanitized_detail or "" for attempt in attempts)
    if failed is not None:
        retained_rows.append(str(failed.sanitized_details_json))
    if conflict is not None:
        retained_rows.append(str(conflict.sanitized_details_json))
    outbox = await db_session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))
    assert outbox is not None
    retained_rows.extend((outbox.sanitized_reason or "", outbox.last_error_category or ""))
    log = await db_session.scalar(
        select(CTMSCoordinationEventLog).where(CTMSCoordinationEventLog.event_id == event.event_id)
    )
    if log is not None:
        retained_rows.append(log.sanitized_reason or "")
    assert case.prohibited_value not in " ".join(retained_rows)
    assert "payload" not in " ".join(retained_rows).lower()
