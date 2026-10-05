"""PV EDC adverse-event reconciliation persistence (Phase 2).

Reconciliation is one-way and read-only. PV compares its own Safety_Cases
against the approved, minimized, read-only ``Safety_Operational_Projection`` of
EDC adverse events (subject reference, verbatim term, onset date, seriousness)
consumed through :mod:`app.models.pv.coordination`. It never creates, allocates,
or mutates an EDC clinical record or a CTMS operational record.

A :class:`ReconciliationRun` records one run scoped to a Study within the acting
user's Authorization_Scope, with the count of matched and differing records. Each
differing record produces one :class:`ReconciliationDiscrepancy` identifying the
affected Safety_Case, the EDC reference, and the reconciled fields that differ
among {subject reference, verbatim term, onset date, seriousness} (Requirements
10.1, 10.2, 10.3). A discrepancy also carries a resolution state with the
resolving actor and timestamp; creating or resolving a discrepancy emits one PV
safety Audit_Event (Requirement 10.7).

Every record uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns,
actor/correlation metadata, and soft-deletion/retention columns from
:mod:`app.models.pv.common`.
"""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pv.common import PVBase

JSONBType = JSONB().with_variant(JSON(), "sqlite")

# Partial-index predicate that excludes soft-deleted rows (Requirement 17.5).
_NOT_DELETED = text("deleted_at IS NULL")

# The reconciled field set compared by ``Reconciliation_Service.diff``
# (Requirement 10.1). A discrepancy names the subset of these fields that differ.
RECONCILED_FIELDS: tuple[str, ...] = (
    "subject_reference",
    "verbatim_term",
    "onset_date",
    "seriousness",
)


class DiscrepancyStatus(enum.StrEnum):
    """Resolution state for a Reconciliation_Discrepancy."""

    OPEN = "Open"
    RESOLVED = "Resolved"


_DISCREPANCY_STATUS_VALUES = "','".join(status.value for status in DiscrepancyStatus)


class ReconciliationRun(PVBase):
    """One study-scoped reconciliation run and its match/discrepancy counts.

    A run compares PV Safety_Cases against the read-only EDC adverse-event
    projection for a Study within the acting user's Authorization_Scope. It is
    PV-owned bookkeeping; it never writes EDC clinical or CTMS operational state.
    """

    __tablename__ = "pv_reconciliation_runs"

    study_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    discrepancies: Mapped[list[ReconciliationDiscrepancy]] = relationship(
        "ReconciliationDiscrepancy", back_populates="run", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "match_count >= 0",
            name="ck_pv_reconciliation_runs_match_count",
        ),
        CheckConstraint(
            "discrepancy_count >= 0",
            name="ck_pv_reconciliation_runs_discrepancy_count",
        ),
        Index(
            "ix_pv_reconciliation_runs_study",
            "study_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_reconciliation_runs_created_at",
            "created_at",
            postgresql_where=_NOT_DELETED,
        ),
    )


class ReconciliationDiscrepancy(PVBase):
    """One differing record found by a reconciliation run.

    The discrepancy identifies the affected Safety_Case (``case_id``), the EDC
    reference (``edc_reference``, the projected source record identifier), and the
    reconciled fields that differ (``differing_fields``, a subset of
    :data:`RECONCILED_FIELDS`). ``status`` tracks resolution; a resolved
    discrepancy records the resolving actor and UTC timestamp.
    """

    __tablename__ = "pv_reconciliation_discrepancies"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False
    )
    edc_reference: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    differing_fields: Mapped[list[str]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DiscrepancyStatus.OPEN.value
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    run: Mapped[ReconciliationRun] = relationship(
        "ReconciliationRun", back_populates="discrepancies", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{_DISCREPANCY_STATUS_VALUES}')",
            name="ck_pv_reconciliation_discrepancies_status",
        ),
        Index(
            "ix_pv_reconciliation_discrepancies_run",
            "run_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_reconciliation_discrepancies_case",
            "case_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_reconciliation_discrepancies_status",
            "status",
            postgresql_where=_NOT_DELETED,
        ),
    )

    @property
    def differing(self) -> list[str]:
        """Return the differing reconciled fields as a list."""

        return list(self.differing_fields or [])


__all__ = [
    "RECONCILED_FIELDS",
    "DiscrepancyStatus",
    "ReconciliationDiscrepancy",
    "ReconciliationRun",
]
