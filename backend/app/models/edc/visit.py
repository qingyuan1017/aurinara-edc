"""Visit models — operational visit instances; definition re-exported.

The design-time ``VisitDefinition`` (a Visit_Definition in the Designer_Module)
was reassigned to the Designer module and now lives in
``app.models.designer.visit``. It is re-exported here so existing import paths
(``from app.models.edc.visit import VisitDefinition``) keep working unchanged
(R11.1 — additive, no breakage) and so the shared ORM registry resolves the
``VisitInstance.visit_definition`` relationship by name.

The operational ``VisitInstance`` (a visit *occurrence* for a Subject) and its
lifecycle status enum stay here — they are Operational_Records owned by the EDC
module (R7, R11.2).

Satisfies Requirements:
  - 4.2-4.4: Visit definitions (now Designer-owned; re-exported).
  - 7.x / 8.2 / 8.3: Visit instances created from a bound design version's visit
          definitions, carrying a window status.
  - 11.1: Ownership reassignment with no table/column renames (stored values
          preserved); FK to ``study_versions`` kept.
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

# Visit definitions are owned by the Designer module. Re-exported here for
# backward compatibility with existing ``app.models.edc.visit`` imports and so
# the shared ORM registry resolves ``VisitInstance.visit_definition`` by name.
from app.models.designer.visit import VisitDefinition

# --- Enums ---


class VisitInstanceStatus(enum.StrEnum):
    """Visit instance lifecycle status (Requirement 8.2, 8.3, 8.5)."""

    not_started = "not_started"
    scheduled = "scheduled"
    in_window = "in_window"
    completed = "completed"
    missed = "missed"
    unscheduled = "unscheduled"
    added_in_error = "added_in_error"


# --- Models ---


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

    # Bound published design version (not-null after backfill — R2.7, R7.3, R11.2)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Binds this operational record to a published design version",
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
    is_user_added: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True for visit occurrences explicitly added by an EDC user",
    )
    data_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    subject: Mapped["Subject"] = relationship("Subject", lazy="selectin")  # noqa: F821
    visit_definition: Mapped["VisitDefinition | None"] = relationship(
        "VisitDefinition", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_visit_instances_subject_id", "subject_id"),
        Index("ix_visit_instances_status", "status"),
        Index("ix_visit_instances_design_version_id", "design_version_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<VisitInstance(id={self.id}, subject_id={self.subject_id}, "
            f"name={self.name!r}, status={self.status!r})>"
        )


__all__ = [
    "VisitDefinition",
    "VisitInstance",
    "VisitInstanceStatus",
]
