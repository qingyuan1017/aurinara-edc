"""Subject_Phase_Transition model — a NEW Designer-owned design-time table.

A ``Subject_Phase_Transition`` is a typed, self-referential edge expressing that
a subject may move from one ``Subject_Phase_Definition`` to another within a
``Draft_Design``. The transitions form the directed graph that the Subject
Phases editor renders (xy-flow style). The edge is self-guarded: a phase cannot
transition to itself (enforced by a DB CHECK and the owning service), and a
``(design_version_id, from_phase_id, to_phase_id)`` triple is unique.

Conventions (mirroring ``visit_dependency.py`` and ``subject_phase_definition.py``):
  - UUID primary key.
  - Bound to exactly one ``Design_Version`` via ``design_version_id``.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column (regulated-record retention).
  - FKs by table name so the shared ORM registry resolves them; the two phase
    FKs cascade on delete and carry NO ORM relationships (only the owning
    ``design_version`` relationship is declared).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
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

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.study_version import StudyVersion


class SubjectPhaseTransition(Base):
    """A design-time subject-phase-to-phase transition edge (self-guarded)."""

    __tablename__ = "subject_phase_transitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (binds the edge to exactly one design version)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The source and target phases of the transition.
    from_phase_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subject_phase_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_phase_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subject_phase_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional presentation label and condition expression driving the edge.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_expression: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps (timezone-aware). ``updated_at`` is kept for parity with the
    # phase-definition table but is intentionally not serialized.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Relationship (resolved by string against the shared ORM registry). No ORM
    # relationships are declared on the two phase FKs by design.
    design_version: Mapped[StudyVersion] = relationship("StudyVersion", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "from_phase_id <> to_phase_id",
            name="ck_subject_phase_transition_not_self",
        ),
        UniqueConstraint(
            "design_version_id",
            "from_phase_id",
            "to_phase_id",
            name="uq_subject_phase_transition",
        ),
        Index(
            "ix_subject_phase_transitions_design_version_id",
            "design_version_id",
        ),
        Index(
            "ix_subject_phase_transitions_from_phase_id",
            "from_phase_id",
        ),
        Index(
            "ix_subject_phase_transitions_to_phase_id",
            "to_phase_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SubjectPhaseTransition(id={self.id}, "
            f"design_version_id={self.design_version_id}, "
            f"from_phase_id={self.from_phase_id}, to_phase_id={self.to_phase_id})>"
        )
