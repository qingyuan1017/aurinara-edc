"""Repository boundary for CTMS coordination events and durable delivery rows."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ctms.coordination import (
    CoordinationEvent,
    CoordinationEventLog,
    CTMSEventAttempt,
    CTMSOutbox,
)


class CoordinationRepository:
    """Persistence seam for coordination state; callers own transactions."""

    async def get_event(self, session: AsyncSession, event_id: UUID) -> CoordinationEvent | None:
        return await session.scalar(
            select(CoordinationEvent).where(
                or_(CoordinationEvent.id == event_id, CoordinationEvent.event_id == event_id)
            )
        )

    async def get_by_idempotency(
        self, session: AsyncSession, *, source_module: str, idempotency_key: str
    ) -> CoordinationEvent | None:
        return await session.scalar(
            select(CoordinationEvent).where(
                CoordinationEvent.source_module == source_module,
                CoordinationEvent.idempotency_key == idempotency_key,
            )
        )

    async def add_event(self, session: AsyncSession, event: CoordinationEvent) -> CoordinationEvent:
        session.add(event)
        await session.flush()
        return event

    async def get_outbox(self, session: AsyncSession, event_id: UUID) -> CTMSOutbox | None:
        return await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event_id))

    async def add_outbox(self, session: AsyncSession, outbox: CTMSOutbox) -> CTMSOutbox:
        session.add(outbox)
        await session.flush()
        return outbox

    async def list_ready_outbox(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[CTMSOutbox]:
        timestamp = now or datetime.now(UTC)
        result = await session.scalars(
            select(CTMSOutbox)
            .where(
                CTMSOutbox.status.in_(("Pending", "Accepted", "accepted", "Queued", "queued", "Retrying", "retrying")),
                CTMSOutbox.available_at <= timestamp,
            )
            .order_by(CTMSOutbox.available_at.asc(), CTMSOutbox.event_id.asc())
            .limit(max(1, int(limit)))
        )
        return result.all()

    async def get_log(self, session: AsyncSession, event_id: UUID) -> CoordinationEventLog | None:
        return await session.scalar(
            select(CoordinationEventLog).where(CoordinationEventLog.event_id == event_id)
        )

    async def add_attempt(self, session: AsyncSession, attempt: CTMSEventAttempt) -> CTMSEventAttempt:
        session.add(attempt)
        await session.flush()
        return attempt

    async def add_log(self, session: AsyncSession, log: CoordinationEventLog) -> CoordinationEventLog:
        session.add(log)
        await session.flush()
        return log


coordination_repository = CoordinationRepository()

__all__ = ["CoordinationRepository", "coordination_repository"]
