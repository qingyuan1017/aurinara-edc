"""Reusable SQLAlchemy conventions for additive CTMS-owned tables.

These mixins describe metadata only. CTMS models reference canonical EDC
identifiers and never duplicate EDC clinical records.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RetentionState(StrEnum):
    """Retention state for a CTMS record."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for SQLAlchemy defaults."""

    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    """UUID primary key for CTMS-owned records."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    """Timezone-aware UTC creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=utc_now
    )


class ActorMetadataMixin:
    """Actor references for CTMS-owned mutations."""

    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class CorrelationMixin:
    """Correlation and idempotency metadata for traceable operations."""

    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )


class RetentionMixin:
    """Archive/retention metadata without cascading into EDC records."""

    retention_state: Mapped[RetentionState] = mapped_column(
        String(30), nullable=False, default=RetentionState.ACTIVE
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SoftDeleteMixin:
    """Logical deletion metadata for CTMS records that support deletion."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CTMSRecordMixin(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    ActorMetadataMixin,
    CorrelationMixin,
    RetentionMixin,
    SoftDeleteMixin,
):
    """Complete common metadata contract for a CTMS-owned record."""


class CTMSBase(CTMSRecordMixin, Base):
    """Abstract base combining the CTMS metadata contract with the platform ORM."""

    __abstract__ = True


CTMS_REFERENCE_AUTHORITY = "canonical EDC or shared platform identity"

__all__ = [
    "CTMS_REFERENCE_AUTHORITY",
    "ActorMetadataMixin",
    "CTMSBase",
    "CTMSRecordMixin",
    "CorrelationMixin",
    "RetentionMixin",
    "RetentionState",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "utc_now",
]
