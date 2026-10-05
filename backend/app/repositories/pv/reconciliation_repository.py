"""Persistence for PV EDC adverse-event reconciliation.

The repository owns SQLAlchemy access for ``pv_reconciliation_runs`` and
``pv_reconciliation_discrepancies``. It only reads and stages ORM objects on the
caller-provided :class:`AsyncSession`; it never commits. The commit/rollback
boundary belongs to the request or worker unit of work so a reconciliation run,
its discrepancies, and their PV safety Audit_Events commit or roll back
together.

Reconciliation is one-way and read-only. This repository reads PV Safety_Cases
and their captured adverse events and reads the approved read-only EDC
adverse-event projection; it never creates, allocates, or mutates an EDC clinical
record or a CTMS operational record.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.reconciliation import (
    ReconciliationDiscrepancy,
    ReconciliationRun,
)
from app.models.pv.safety_case import AdverseEventRecord, SafetyCase


class ReconciliationRepository:
    """Repository seam for PV reconciliation runs and discrepancies."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def cases_for_study(self, study_id: UUID) -> list[SafetyCase]:
        """Return the live Safety_Cases for a study with their adverse events.

        Cases are returned in a deterministic order (creation time then id) so a
        run compares records predictably.
        """

        statement = (
            select(SafetyCase)
            .where(
                SafetyCase.study_id == study_id,
                SafetyCase.deleted_at.is_(None),
            )
            .order_by(SafetyCase.created_at, SafetyCase.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def adverse_events_for_case(self, case_id: UUID) -> list[AdverseEventRecord]:
        """Return the live Adverse_Event_Records captured under a Safety_Case."""

        statement = (
            select(AdverseEventRecord)
            .where(
                AdverseEventRecord.case_id == case_id,
                AdverseEventRecord.deleted_at.is_(None),
            )
            .order_by(AdverseEventRecord.created_at, AdverseEventRecord.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_run(
        self, run_id: UUID, *, include_deleted: bool = False
    ) -> ReconciliationRun | None:
        """Load a reconciliation run by id, excluding soft-deleted rows."""

        statement = select(ReconciliationRun).where(ReconciliationRun.id == run_id)
        if not include_deleted:
            statement = statement.where(ReconciliationRun.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_discrepancy(
        self, discrepancy_id: UUID, *, include_deleted: bool = False
    ) -> ReconciliationDiscrepancy | None:
        """Load a discrepancy by id, excluding soft-deleted rows."""

        statement = select(ReconciliationDiscrepancy).where(
            ReconciliationDiscrepancy.id == discrepancy_id
        )
        if not include_deleted:
            statement = statement.where(ReconciliationDiscrepancy.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_run(
        self,
        *,
        study_id: UUID,
        match_count: int,
        discrepancy_count: int,
        run_at: datetime,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> ReconciliationRun:
        """Stage one reconciliation run and flush."""

        run = ReconciliationRun(
            study_id=study_id,
            match_count=match_count,
            discrepancy_count=discrepancy_count,
            run_at=run_at,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def add_discrepancy(
        self,
        *,
        run_id: UUID,
        case_id: UUID,
        edc_reference: UUID | None,
        differing_fields: Sequence[str],
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> ReconciliationDiscrepancy:
        """Stage one discrepancy and flush."""

        discrepancy = ReconciliationDiscrepancy(
            run_id=run_id,
            case_id=case_id,
            edc_reference=edc_reference,
            differing_fields=list(differing_fields),
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(discrepancy)
        await self.session.flush()
        return discrepancy

    async def flush(self) -> None:
        await self.session.flush()


__all__ = ["ReconciliationRepository"]
