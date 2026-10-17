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
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.odm_oid import new_odm_oid

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
    odm_oid: Mapped[str] = mapped_column(
        String(255), nullable=False, default=lambda: new_odm_oid("SE")
    )

    # Visit metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    visit_number: Mapped[int] = mapped_column(Integer, nullable=False)
    visit_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="visit",
        server_default="visit",
        comment="discriminator: visit | cycle (also scheduled/unscheduled/screening)",
    )
    definition_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="visit",
        server_default="visit",
        comment="visit | folder | cycle",
    )
    parent_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subtype: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Cycle-only metadata (nullable for all rows; only meaningful when
    # ``visit_type == 'cycle'``). A plain visit never sets these; the service
    # layer owns the "repeat/cycle_length only when visit_type == 'cycle'" rule.
    repeat_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="cycle-only: minimum repeat count"
    )
    repeat_max: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="cycle-only: maximum repeat count"
    )
    cycle_length: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="cycle-only: nominal length in days of one iteration",
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
    addable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether EDC users may add another instance of this visit definition",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    study_version: Mapped[StudyVersion] = relationship("StudyVersion", lazy="selectin")
    parent_folder: Mapped[VisitDefinition | None] = relationship(
        "VisitDefinition",
        remote_side="VisitDefinition.id",
        foreign_keys=[parent_folder_id],
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "NOT addable OR definition_kind IN ('visit', 'cycle_visit')",
            name="ck_visit_definitions_addable_real_visit",
        ),
        Index("ix_visit_definitions_study_version_id", "study_version_id"),
        Index("ix_visit_definitions_visit_type", "visit_type"),
        Index("ix_visit_definitions_definition_kind", "definition_kind"),
        Index("ix_visit_definitions_parent_folder_id", "parent_folder_id"),
        Index("ix_visit_definitions_odm_oid", "odm_oid"),
    )

    def __repr__(self) -> str:
        return (
            f"<VisitDefinition(id={self.id}, name={self.name!r}, visit_number={self.visit_number})>"
        )
