"""Study and study version models.

Satisfies Requirements:
  - 4.1: Study metadata — code, protocol number, title, sponsor, phase, therapeutic area,
          indication, status.
  - 4.2: Globally unique study code.
  - 5.1: Study versions with draft/published lifecycle.
  - 5.5: Each form definition is associated with exactly one Study_Version (via FK).
  - 22.1: UUID primary keys.
  - 22.5: Soft-delete via deleted_at column.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --- Enums ---


class StudyStatus(enum.StrEnum):
    """Study lifecycle status (Requirement 4.3)."""

    draft = "Draft"
    uat = "UAT"
    active = "Active"
    enrollment_closed = "Enrollment Closed"
    locked = "Locked"
    archived = "Archived"


class StudyVersionStatus(enum.StrEnum):
    """Study version status (Requirement 5.1)."""

    draft = "draft"
    published = "published"


# --- Models ---


class Study(Base):
    """Clinical study/trial — the top-level organizational entity."""

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
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft-delete (Requirement 22.5)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

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


class StudyVersion(Base):
    """Versioned snapshot of a study's metadata definitions.

    Each published version is immutable; form/visit/field definitions reference
    a specific version. New drafts are created for amendments (Requirement 5.3).
    """

    __tablename__ = "study_versions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Parent study
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )

    # Version identifier
    version_number: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="e.g. 1.0, 2.0"
    )

    # Lifecycle
    status: Mapped[StudyVersionStatus] = mapped_column(
        String(20), nullable=False, default=StudyVersionStatus.draft
    )

    # Amendment info (Phase 3)
    amendment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Publication
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    study: Mapped["Study"] = relationship("Study", back_populates="versions")

    __table_args__ = (
        UniqueConstraint("study_id", "version_number", name="uq_study_version_number"),
        Index("ix_study_versions_study_id", "study_id"),
        Index("ix_study_versions_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudyVersion(id={self.id}, study_id={self.study_id}, "
            f"version={self.version_number!r}, status={self.status!r})>"
        )
