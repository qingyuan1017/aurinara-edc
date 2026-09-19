"""Scheduled CTMS retention worker entry point."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ctms_retention_service import RetentionRunResult, ctms_retention_service

WORKER_NAME = "ctms-retention"


async def run_ctms_retention(
    session: AsyncSession,
    *,
    actor_id: UUID | str,
    reason: str = "Configured CTMS retention policy",
    now: datetime | None = None,
) -> RetentionRunResult:
    """Run one bounded retention pass in the caller's transaction."""
    return await ctms_retention_service.run(
        session,
        actor_id=actor_id,
        reason=reason,
        now=now,
    )


class CTMSRetentionWorker:
    """Small scheduler-facing wrapper; scheduling remains deployment-owned."""

    async def run(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID | str,
        reason: str = "Configured CTMS retention policy",
        now: datetime | None = None,
    ) -> RetentionRunResult:
        return await run_ctms_retention(session, actor_id=actor_id, reason=reason, now=now)


ctms_retention_worker = CTMSRetentionWorker()

__all__ = ["WORKER_NAME", "CTMSRetentionWorker", "ctms_retention_worker", "run_ctms_retention"]
