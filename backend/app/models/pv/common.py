"""Reusable SQLAlchemy conventions for additive PV_Safety_Module tables.

These mixins describe metadata only. PV safety models reference canonical
Study/Site identity and the EDC ``Subject_Reference``/``Visit_Instance``
identity; they never duplicate or mutate EDC clinical records or CTMS
operational records. Every PV-owned record uses a UUID primary key,
timezone-aware UTC timestamps with at least one-second precision,
study/site scope, actor/correlation metadata, retention state, and
soft-deletion fields (deletion actor, timestamp, reason).
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RetentionState(StrEnum):
    """Retention state for a PV safety record."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


class ProjectionStatus(StrEnum):
    """Freshness of a read-only EDC adverse-event projection consumed by PV."""

    CURRENT = "Current"
    STALE = "Stale"
    REJECTED = "Rejected"


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for SQLAlchemy defaults."""

    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    """UUID primary key for PV-owned records."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    """Timezone-aware UTC creation and update timestamps (>= one-second precision)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ActorMetadataMixin:
    """Actor references for PV-owned mutations."""

    created_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CorrelationMixin:
    """Correlation and idempotency metadata for traceable safety operations."""

    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class RetentionMixin:
    """Archive/retention metadata without cascading into EDC/CTMS records."""

    retention_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RetentionState.ACTIVE.value
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SoftDeleteMixin:
    """Logical deletion metadata for PV records that support deletion.

    PV never physically removes Safety_Data or a related Audit_Event; deletion
    retains the acting user, timestamp, and reason for attribution.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PVRecordMixin(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    ActorMetadataMixin,
    CorrelationMixin,
    RetentionMixin,
    SoftDeleteMixin,
):
    """Complete common metadata contract for a PV-owned safety record."""


class PVBase(PVRecordMixin, Base):
    """Abstract base combining the PV metadata contract with the platform ORM."""

    __abstract__ = True


# PV references canonical identity owned elsewhere; it never becomes the
# authority for these references.
PV_REFERENCE_AUTHORITY = "canonical Study/Site and EDC Subject_Reference identity"

__all__ = [
    "PV_REFERENCE_AUTHORITY",
    "ActorMetadataMixin",
    "CorrelationMixin",
    "PVBase",
    "PVRecordMixin",
    "ProjectionStatus",
    "RetentionMixin",
    "RetentionState",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "utc_now",
]
