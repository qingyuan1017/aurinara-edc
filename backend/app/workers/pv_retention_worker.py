"""Scheduled PV retention worker entry point.

The worker runs one bounded PV retention pass in the caller's transaction. Its
scheduling remains deployment-owned; the worker only enforces the configured PV
retention/archival policy over PV-owned records and never cascades into EDC
clinical or CTMS operational data (Requirement 20.3, design "Migration and
integrity plan" step 6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pv_retention_service import RetentionRunResult, pv_retention_service

WORKER_NAME = "pv-retention"

_DEFAULT_REASON = "Configured PV safety retention policy"


async def run_pv_retention(
    session: AsyncSession,
    *,
    actor_id: UUID | str,
    reason: str = _DEFAULT_REASON,
    now: datetime | None = None,
) -> RetentionRunResult:
    """Run one bounded PV retention pass in the caller's transaction."""

    return await pv_retention_service.run(
        session,
        actor_id=actor_id,
        reason=reason,
        now=now,
    )


class PVRetentionWorker:
    """Small scheduler-facing wrapper; scheduling remains deployment-owned."""

    async def run(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID | str,
        reason: str = _DEFAULT_REASON,
        now: datetime | None = None,
    ) -> RetentionRunResult:
        return await run_pv_retention(session, actor_id=actor_id, reason=reason, now=now)


pv_retention_worker = PVRetentionWorker()

__all__ = ["WORKER_NAME", "PVRetentionWorker", "pv_retention_worker", "run_pv_retention"]
