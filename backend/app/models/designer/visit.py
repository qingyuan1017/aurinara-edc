"""Designer-owned visit definition model.

``VisitDefinition`` is a design-time artifact (a Visit_Definition in the
Designer_Module): it describes a scheduled visit — name, visit number, type,
target day, and window bounds — and belongs to a ``Design_Version``
(``study_versions``). It was reassigned from the EDC module to the Designer
module as part of the Designer / EDC refactor.

The operational ``VisitInstance`` (a visit *occurrence* for a Subject) stays in
the EDC module (``app.models.edc.visit``); only the design-time definition moves
here.

The move is a **code-layer ownership change only** — the backing table
(``visit_definitions``) and all columns are unchanged, so stored values are
preserved and the migration is purely additive (R11.1). The FK to
``study_versions`` is kept intact.

Satisfies Requirements:
  - 4.2: Visit definitions - name (1-100), visit number (1-9999), target day
          (0-99999), and integer window bounds (0-99999, lower <= upper).
  - 4.3: The invalid-window rule (lower > upper) is enforced at the service
          layer; the model persists only valid definitions.
  - 11.1: Ownership reassignment with no table/column renames (stored values
          preserved); FK to ``study_versions`` kept.
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid runtime import cycles across module boundaries
    from app.models.designer.study_version import StudyVersion


class VisitDefinition(Base):
    """Definition of a study visit within a Design_Version (Requirement 4.2).

    Visit definitions belong to a ``Design_Version`` (``study_versions``) and are
    immutable once the owning version is published.
    """

    __tablename__ = "visit_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version
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
    study_version: Mapped[StudyVersion] = relationship(
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
