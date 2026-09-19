"""Durable CTMS coordination worker primitives.

The worker is deliberately separate from request transactions. It claims only
outbox rows and never waits in the request path; unavailable workers leave
accepted rows pending for later recovery.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.ctms.coordination import CoordinationEvent, CTMSOutbox
from app.services.coordination_service import (
    CoordinationResult,
    classify_failure,
    coordination_service,
)
from app.services.ctms_health_service import ctms_health_service

WORKER_NAME = "ctms-coordination"


class CoordinationWorker:
    """Claim and complete durable coordination events with bounded attempts."""

    def __init__(self, *, max_attempts: int = 3) -> None:
        self.max_attempts = max(1, int(max_attempts))

    async def claim_pending(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[CTMSOutbox]:
        """Claim ready rows in deterministic order without waiting on a lock."""
        if ctms_health_service.worker_status == "unavailable":
            return []
        timestamp = now or datetime.now(UTC)
        result = await session.execute(
            select(CTMSOutbox)
            .where(
                CTMSOutbox.status.in_(
                    ("Pending", "Accepted", "accepted", "Queued", "queued", "Retrying", "retrying")
                ),
                CTMSOutbox.available_at <= timestamp,
            )
            .order_by(CTMSOutbox.available_at.asc(), CTMSOutbox.event_id.asc())
            .limit(max(1, min(int(limit), coordination_service.queue.capacity)))
        )
        rows = list(result.scalars().all())
        claimed: list[CTMSOutbox] = []
        for row in rows:
            if not coordination_service.queue.try_enqueue(row.event_id):
                break
            row.status = "Processing"
            row.claimed_at = timestamp
            row.attempt_count = int(row.attempt_count or 0) + 1
            claimed.append(row)
        await session.flush()
        return claimed

    async def mark_processed(
        self,
        session: AsyncSession,
        event: CTMSOutbox,
        *,
        processed_at: datetime | None = None,
    ) -> CTMSOutbox:
        processed = processed_at or datetime.now(UTC)
        event.status = "Published"
        event.outcome = event.outcome or "succeeded"
        event.processed_at = processed
        event.published_at = processed
        if event.coordination_event_id is not None:
            coordination_event = await session.scalar(
                select(CoordinationEvent).where(CoordinationEvent.event_id == event.coordination_event_id)
            )
            if coordination_event is not None:
                coordination_event.status = "succeeded"
                coordination_event.processed_at = processed
                coordination_event.sanitized_reason = event.sanitized_reason
                coordination_event.resulting_projection_id = event.resulting_projection_id
        await session.flush()
        coordination_service.processed(event.event_id)
        return event

    async def mark_failed(
        self,
        session: AsyncSession,
        event: CTMSOutbox,
        *,
        reason: str,
    ) -> CTMSOutbox:
        """Retry only retryable rows within the bound, then retain a sanitized outcome."""
        classification = classify_failure(reason)
        if classification.retryable and int(event.attempt_count or 0) < self.max_attempts:
            delay = min(
                int(get_settings().ctms_coordination_backoff_max_seconds),
                int(get_settings().ctms_coordination_backoff_base_seconds)
                * (2 ** max(0, int(event.attempt_count or 1) - 1)),
            )
            event.status = "Retrying"
            event.last_error_category = classification.code
            event.sanitized_reason = classification.code
            event.available_at = datetime.now(UTC) + timedelta(seconds=max(1, delay))
            await session.flush()
            return event
        failure_code = classification.code
        if (
            not classification.retryable
            and not classification.conflict
            and reason.isupper()
            and reason.replace("_", "").isalnum()
        ):
            failure_code = reason[:100]
        return await coordination_service.failed_event(session, event, reason=failure_code)

    async def mark_conflict(
        self,
        session: AsyncSession,
        event: CTMSOutbox,
        *,
        reason: str,
    ) -> CTMSOutbox:
        return await coordination_service.conflict_event(session, event, reason=reason)

    async def process_event(
        self,
        session: AsyncSession,
        *,
        event_id,
        worker_id: str = WORKER_NAME,
    ) -> CoordinationResult:
        """Run deterministic event processing in the worker transaction."""
        return await coordination_service.process(
            session,
            event_id=event_id,
            worker_id=worker_id,
        )

    def unavailable(self) -> None:
        """Mark outage without touching durable accepted events."""
        coordination_service.worker_unavailable()

    def available(self) -> None:
        coordination_service.worker_available()


coordination_worker = CoordinationWorker()

__all__ = ["WORKER_NAME", "CoordinationWorker", "coordination_worker"]
