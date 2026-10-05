"""PV read-only EDC adverse-event projection and coordination reference records (Phase 2).

PV consumes ``EDC_Adverse_Events`` only through an approved, minimized, read-only
``Safety_Operational_Projection`` delivered by the shared ``Coordination_Service``
transactional outbox. This module persists that consumed projection read model
and the coordination references that keep projected EDC records traceable by
correlation identifier.

Both tables are read-only for PV: nothing here creates, allocates, or mutates an
EDC clinical record or a CTMS operational record. ``pv_edc_ae_projections`` stores
only the approved minimized field set (subject reference, verbatim term, onset
date, seriousness) plus the source identifier, rule version, correlation
identifier, projected timestamp, payload fingerprint, and projection status
(``Current``/``Stale``/``Rejected``). ``pv_coordination_refs`` records the
coordination event references by correlation identifier so projected EDC
references remain traceable without duplicating clinical records (Requirement
17.6).

Every record uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns,
actor/correlation metadata, and soft-deletion/retention columns from
:mod:`app.models.pv.common`.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy import (
    Uuid as SAUuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.pv.common import ProjectionStatus, PVBase

# Partial-index predicate that excludes soft-deleted rows (Requirement 17.5).
_NOT_DELETED = text("deleted_at IS NULL")

# The only projection statuses PV persists for a consumed EDC adverse-event
# projection read model (Requirement 23.6, design "Coordination and read-only
# projection consumption").
_PROJECTION_STATUS_VALUES = "','".join(status.value for status in ProjectionStatus)

# The approved minimized field set released to PV for reconciliation
# (subject reference, verbatim term, onset date, seriousness). Any field outside
# this allowlist is rejected before it can be persisted (Requirements 10.4,
# 23.6, 23.7).
APPROVED_PROJECTION_FIELDS: tuple[str, ...] = (
    "subject_reference",
    "verbatim_term",
    "onset_date",
    "seriousness",
)


class EdcAeProjection(PVBase):
    """A minimized, read-only projection of one EDC adverse event.

    The record holds only the approved reconciled field set and its coordination
    provenance. ``projection_status`` is ``Current`` for the freshest accepted
    projection of a source record, ``Stale`` when superseded by a newer source
    version, and ``Rejected`` when an unapproved/unauthorized projection request
    was recorded without content. The record is read-only for PV: no PV path
    writes it back into EDC clinical state.
    """

    __tablename__ = "pv_edc_ae_projections"

    # --- Coordination provenance ------------------------------------------
    source_module: Mapped[str] = mapped_column(String(20), nullable=False, default="EDC")
    source_record_id: Mapped[UUID] = mapped_column(SAUuid, nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProjectionStatus.CURRENT.value
    )

    # --- Optional scope for authorization-scoped reconciliation -----------
    study_id: Mapped[UUID | None] = mapped_column(SAUuid, nullable=True)
    site_id: Mapped[UUID | None] = mapped_column(SAUuid, nullable=True)

    # --- Approved minimized reconciled field set --------------------------
    # ``subject_reference`` references the EDC clinical Subject identity read-only;
    # PV never owns or mutates that identity. The remaining fields carry the
    # projected verbatim term, onset date, and seriousness for reconciliation.
    subject_reference: Mapped[UUID | None] = mapped_column(SAUuid, nullable=True)
    verbatim_term: Mapped[str | None] = mapped_column(String(200), nullable=True)
    onset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    seriousness: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # --- Denial bookkeeping for a rejected projection request -------------
    rejection_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"projection_status IN ('{_PROJECTION_STATUS_VALUES}')",
            name="ck_pv_edc_ae_projections_status",
        ),
        CheckConstraint(
            "verbatim_term IS NULL OR length(verbatim_term) BETWEEN 1 AND 200",
            name="ck_pv_edc_ae_projections_verbatim_length",
        ),
        # At-least-once delivery is deduplicated by idempotency key among live
        # rows so re-delivery of the same event upserts one projection.
        Index(
            "uq_pv_edc_ae_projections_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_edc_ae_projections_source",
            "source_module",
            "source_record_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_edc_ae_projections_scope_status",
            "study_id",
            "site_id",
            "projection_status",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_edc_ae_projections_correlation",
            "correlation_id",
            postgresql_where=_NOT_DELETED,
        ),
    )

    @property
    def read_only(self) -> bool:
        """Projections are always read-only for PV."""

        return True


class CoordinationRef(PVBase):
    """A traceable reference to a consumed coordination event.

    PV persists coordination event references by correlation identifier so a
    projected EDC reference stays traceable without duplicating the EDC clinical
    record (Requirement 17.6). The row records the source event identity, the
    idempotency key, the processing outcome, and the resulting projection when
    one was upserted.
    """

    __tablename__ = "pv_coordination_refs"

    event_id: Mapped[UUID] = mapped_column(SAUuid, nullable=False)
    source_module: Mapped[str] = mapped_column(String(20), nullable=False, default="EDC")
    source_record_id: Mapped[UUID] = mapped_column(SAUuid, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    sanitized_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    projection_id: Mapped[UUID | None] = mapped_column(
        SAUuid, ForeignKey("pv_edc_ae_projections.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Processing is idempotent per source event; one completed reference row
        # per idempotency key among live rows.
        Index(
            "uq_pv_coordination_refs_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_coordination_refs_correlation",
            "correlation_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_coordination_refs_source",
            "source_module",
            "source_record_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


__all__ = [
    "APPROVED_PROJECTION_FIELDS",
    "CoordinationRef",
    "EdcAeProjection",
]
