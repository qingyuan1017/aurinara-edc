"""Visit definition and visit instance models.

Satisfies Requirements:
  - 8.1: Visit definitions — name, visit number, visit type, target day, window bounds,
          display order, required flag.
  - 8.2: Visit instances created from a bound study version's visit definitions.
  - 8.3: Visit instances carry a window status (before_window, in_window, after_window).
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --- Enums ---


class VisitInstanceStatus(enum.StrEnum):
    """Visit instance lifecycle status (Requirement 8.2, 8.3, 8.5)."""

    not_started = "not_started"
    scheduled = "scheduled"
    in_window = "in_window"
    completed = "completed"
    missed = "missed"
    unscheduled = "unscheduled"


# --- Models ---


class VisitDefinition(Base):
    """Definition of a study visit within a study version (Requirement 8.1).

    Visit definitions belong to a Study_Version and are immutable once the
    owning version is published.
    """

    __tablename__ = "visit_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning study version
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )

    # Visit metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    visit_number: Mapped[int] = mapped_column(Integer, nullable=False)
    visit_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="e.g. scheduled, unscheduled, screening",
    )

    # Window definition (relative to baseline)
    target_day: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Day relative to baseline"
    )
    window_before: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Days before target"
    )
    window_after: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Days after target"
    )

    # Ordering and requirement
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    study_version: Mapped["StudyVersion"] = relationship(  # noqa: F821
        "StudyVersion", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_visit_definitions_study_version_id", "study_version_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<VisitDefinition(id={self.id}, name={self.name!r}, "
            f"visit_number={self.visit_number})>"
        )


class VisitInstance(Base):
    """A scheduled or unscheduled visit occurrence for a Subject (Requirement 8.2)."""

    __tablename__ = "visit_instances"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning subject
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    # Source visit definition (nullable for unscheduled visits)
    visit_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="SET NULL"),
        nullable=True,
        comment="Null for unscheduled visits",
    )

    # Visit metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Occurrence data
    visit_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="Recorded when the visit occurs"
    )
    window_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="before_window, in_window, after_window",
    )

    # Lifecycle
    status: Mapped[VisitInstanceStatus] = mapped_column(
        String(20), nullable=False, default=VisitInstanceStatus.not_started
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    subject: Mapped["Subject"] = relationship("Subject", lazy="selectin")  # noqa: F821
    visit_definition: Mapped["VisitDefinition | None"] = relationship(
        "VisitDefinition", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_visit_instances_subject_id", "subject_id"),
        Index("ix_visit_instances_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<VisitInstance(id={self.id}, subject_id={self.subject_id}, "
            f"name={self.name!r}, status={self.status!r})>"
        )
