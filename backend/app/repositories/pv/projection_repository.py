"""Persistence for the PV read-only EDC adverse-event projection read model.

The repository owns SQLAlchemy access for ``pv_edc_ae_projections`` and
``pv_coordination_refs``. It only reads and stages ORM objects on the
caller-provided :class:`AsyncSession`; it never commits. The commit/rollback
boundary belongs to the worker unit of work so the upserted projection, its
coordination reference, and any PV safety Audit_Event commit or roll back
together.

Projections are read-only for PV: this repository never mutates an EDC clinical
record or a CTMS operational record. It reads the shared coordination outbox to
claim work but only advances the outbox row's own delivery bookkeeping.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ctms.coordination import CTMSOutbox
from app.models.pv.coordination import CoordinationRef, EdcAeProjection


class ProjectionRepository:
    """Repository seam for PV projection consumption."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Outbox claiming (shared Coordination_Service transactional outbox)
    # ------------------------------------------------------------------

    async def claim_one_pending(
        self, *, now: datetime, target_module: str = "PV"
    ) -> CTMSOutbox | None:
        """Claim one ready PV-targeted outbox event in deterministic order.

        The row is marked ``Processing`` and its attempt counter is incremented
        so a re-run does not double-claim the same event. Only PV-targeted
        events are consumed; EDC/CTMS delivery is untouched.
        """

        statement = (
            select(CTMSOutbox)
            .where(
                CTMSOutbox.target_module == target_module,
                CTMSOutbox.status.in_(
                    ("Pending", "Accepted", "accepted", "Queued", "queued", "Retrying", "retrying")
                ),
                CTMSOutbox.available_at <= now,
            )
            .order_by(CTMSOutbox.available_at.asc(), CTMSOutbox.event_id.asc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = "Processing"
        row.claimed_at = now
        row.attempt_count = int(row.attempt_count or 0) + 1
        await self.session.flush()
        return row

    async def mark_outbox_outcome(
        self,
        event: CTMSOutbox,
        *,
        outcome: str,
        status: str,
        processed_at: datetime,
        resulting_projection_id: UUID | None = None,
        sanitized_reason: str | None = None,
    ) -> CTMSOutbox:
        """Advance the claimed outbox row to its terminal delivery state."""

        event.status = status
        event.outcome = outcome
        event.processed_at = processed_at
        event.published_at = processed_at
        if resulting_projection_id is not None:
            event.resulting_projection_id = resulting_projection_id
        if sanitized_reason is not None:
            event.sanitized_reason = sanitized_reason
        self.session.add(event)
        await self.session.flush()
        return event

    # ------------------------------------------------------------------
    # Idempotency / staleness lookups
    # ------------------------------------------------------------------

    async def get_ref_by_idempotency_key(self, idempotency_key: str) -> CoordinationRef | None:
        """Return a live coordination reference for an idempotency key, if any."""

        statement = select(CoordinationRef).where(
            CoordinationRef.idempotency_key == idempotency_key,
            CoordinationRef.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_current_projection_for_source(
        self, *, source_module: str, source_record_id: UUID
    ) -> EdcAeProjection | None:
        """Return the current live projection for a source record, if any."""

        statement = select(EdcAeProjection).where(
            EdcAeProjection.source_module == source_module,
            EdcAeProjection.source_record_id == source_record_id,
            EdcAeProjection.projection_status == "Current",
            EdcAeProjection.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def current_projections_for_study(
        self, study_id: UUID
    ) -> list[EdcAeProjection]:
        """Return the live, current projections scoped to a study.

        Used by one-way, read-only reconciliation to compare Safety_Cases against
        the approved minimized EDC adverse-event projection for a Study. Only
        ``Current`` (freshest accepted) live rows are returned so a ``Stale`` or
        ``Rejected`` projection never enters reconciliation.
        """

        statement = (
            select(EdcAeProjection)
            .where(
                EdcAeProjection.study_id == study_id,
                EdcAeProjection.projection_status == "Current",
                EdcAeProjection.deleted_at.is_(None),
            )
            .order_by(EdcAeProjection.projected_at, EdcAeProjection.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_projection_by_idempotency_key(
        self, idempotency_key: str
    ) -> EdcAeProjection | None:
        """Return a live projection previously upserted for an idempotency key."""

        statement = select(EdcAeProjection).where(
            EdcAeProjection.idempotency_key == idempotency_key,
            EdcAeProjection.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Projection and reference staging
    # ------------------------------------------------------------------

    def add_projection(self, projection: EdcAeProjection) -> EdcAeProjection:
        """Stage a new projection row (flushed by the caller)."""

        self.session.add(projection)
        return projection

    def add_ref(self, ref: CoordinationRef) -> CoordinationRef:
        """Stage a coordination reference row (flushed by the caller)."""

        self.session.add(ref)
        return ref

    async def flush(self) -> None:
        await self.session.flush()


__all__ = ["ProjectionRepository"]
