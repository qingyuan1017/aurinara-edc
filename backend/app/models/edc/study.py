"""Study identity model (canonical/shared) and backward-compatible re-exports.

``Study`` is the **canonical, shared** identity for a clinical study. It stays
here and is not redefined elsewhere — the Designer / EDC refactor keeps a single
authoritative ``Study`` identity (no competing identity, R1.5).

The **design-time version metadata** (``Design_Version``) was reassigned to the
Designer module and now lives in ``app.models.designer.study_version``. The
``StudyVersion`` and ``StudyVersionStatus`` symbols are re-exported from this
module so existing import paths (``from app.models.edc.study import
StudyVersion``) continue to work unchanged (R11.1 — additive, no breakage).

Satisfies Requirements:
  - 1.5: `Study` identity canonical/shared (no competing identity).
  - 4.1: Study metadata — code, protocol number, title, sponsor, phase, therapeutic area,
          indication, status.
  - 4.2: Globally unique study code.
  - 11.1: Ownership reassignment of version metadata without table/column renames.
  - 22.1: UUID primary keys.
  - 22.5: Soft-delete via deleted_at column.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Design-time version metadata is owned by the Designer module. Re-exported here
# for backward compatibility with existing ``app.models.edc.study`` imports and
# so the shared ORM registry resolves the ``Study.versions`` relationship.
from app.models.designer.study_version import (
    StudyVersion,
    StudyVersionStatus,
)

# --- Enums ---


class StudyStatus(enum.StrEnum):
    """Study lifecycle status (Requirement 4.3)."""

    draft = "Draft"
    uat = "UAT"
    active = "Active"
    enrollment_closed = "Enrollment Closed"
    locked = "Locked"
    archived = "Archived"


# --- Models ---


class Study(Base):
    """Clinical study/trial — the top-level organizational entity.

    This is the canonical, shared ``Study`` identity. Design-time version
    metadata is modeled by ``Design_Version`` (``StudyVersion``) in the Designer
    module; this identity binds to those versions through the ``versions``
    relationship.
    """

    __tablename__ = "studies"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Study identifiers
    study_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="Globally unique study code"
    )
    protocol_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Sponsor and classification
    sponsor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phase: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="e.g. Phase I, Phase II, Phase III, Phase IV"
    )
    therapeutic_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indication: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Lifecycle
    status: Mapped[StudyStatus] = mapped_column(
        String(30), nullable=False, default=StudyStatus.draft
    )

    # Ownership / audit
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft-delete (Requirement 22.5)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Read-only canonical identity projection owned by aurinara-platform.
    platform_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    platform_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    platform_registry_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Relationships
    versions: Mapped[list["StudyVersion"]] = relationship(
        "StudyVersion", back_populates="study", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_studies_study_code", "study_code", unique=True),
        Index("ix_studies_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Study(id={self.id}, study_code={self.study_code!r}, status={self.status!r})>"


# Backward-compatible public surface. ``StudyVersion`` / ``StudyVersionStatus``
# are owned by ``app.models.designer.study_version`` and re-exported here.
__all__ = [
    "Study",
    "StudyStatus",
    "StudyVersion",
    "StudyVersionStatus",
]
