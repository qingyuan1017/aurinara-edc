"""Worker for consuming approved read-only EDC adverse-event projections.

The worker claims one PV-targeted coordination outbox event, delegates to the
:class:`~app.services.pv_projection_service.PVProjectionService` to revalidate
the active ``Status_Ownership_Rule`` and field allowlist, and upserts only the
PV-side read-only projection read model idempotently by ``Idempotency_Key``. It
records the processing outcome and never lets a stale event overwrite a current
projection.

The worker never opens a write path into EDC clinical or CTMS operational state.
It runs on its own worker transaction, separate from any request path: the
claimed projection, its coordination reference, and the PV safety Audit_Event
commit or roll back together at the worker unit-of-work boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pv_projection_service import (
    ProjectionResult,
    PVProjectionService,
    pv_projection_service,
)

WORKER_NAME = "pv-projection"


class PVProjectionWorker:
    """Claim and process one PV projection outbox event per invocation."""

    def __init__(self, service: PVProjectionService | None = None) -> None:
        self._service = service or pv_projection_service

    async def process_next(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        worker_id: str = WORKER_NAME,
    ) -> ProjectionResult | None:
        """Claim one ready projection event and process it idempotently.

        Returns ``None`` when no PV-targeted event is ready to process. The
        caller owns the transaction commit so the projection upsert, the
        coordination reference, and the PV safety Audit_Event persist atomically.
        """

        from app.repositories.pv.projection_repository import ProjectionRepository

        moment = now or datetime.now(UTC)
        repository = ProjectionRepository(session)
        event = await repository.claim_one_pending(now=moment)
        if event is None:
            return None
        try:
            return await self._service.process_event(
                session, event, worker_id=worker_id, now=moment
            )
        except Exception:
            # Record only that a PV worker job failed; never retain event
            # content, payloads, or the exception detail in the metric.
            from app.services.pv_observability_service import pv_observability_service

            pv_observability_service.record_worker_failure()
            raise


pv_projection_worker = PVProjectionWorker()

__all__ = ["WORKER_NAME", "PVProjectionWorker", "pv_projection_worker"]
