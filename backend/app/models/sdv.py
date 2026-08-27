"""SDV (Source Data Verification) status model.

Satisfies Requirements:
  - 14.1: Persists verified status at field/form/visit/subject scope.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --- Enums ---


class SDVScopeType(enum.StrEnum):
    """Allowed scope types for SDV verification (Requirement 14.1)."""

    field = "field"
    form = "form"
    visit = "visit"
    subject = "subject"


# --- Models ---


class SDVStatus(Base):
    """Tracks source data verification status for a scoped entity.

    A single SDV record is maintained per (scope_type, scope_id) pair.
    Verification can be set or cleared, with the actor and timestamp recorded.
    """

    __tablename__ = "sdv_status"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Scope identification
    scope_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Scope level: field, form, visit, or subject",
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        comment="ID of the scoped entity (field_value, form_instance, visit_instance, or subject)",
    )

    # Verification state
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Verification actor
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    verifier: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[verified_by], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", name="uq_sdv_status_scope"),
        Index("ix_sdv_status_scope_type_scope_id", "scope_type", "scope_id"),
        Index("ix_sdv_status_verified_by", "verified_by"),
    )

    def __repr__(self) -> str:
        return (
            f"<SDVStatus(id={self.id}, scope_type={self.scope_type!r}, "
            f"scope_id={self.scope_id}, is_verified={self.is_verified})>"
        )
