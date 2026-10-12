"""Subject_Phase_Definition model — a NEW Designer-owned design-time table.

A ``Subject_Phase_Definition`` describes a phase of subject participation (for
example screening, treatment, follow-up) authored inside a ``Draft_Design`` and
consumed downstream by operational subject phase tracking. This is a **new**
designer table (not a reassignment of an existing EDC table), bound to exactly
one ``Design_Version`` through ``design_version_id``.

Satisfies Requirements:
  - 3.1: Persist a phase definition with a name of 1-100 characters that is
         unique within its Draft_Design and a display order of 1-999.
  - 3.2: Name uniqueness within a design version is enforced (duplicate names
         are rejected by the owning service, backed by the unique constraint
         below).
  - 3.3: Each Subject_Phase_Definition binds to exactly one Design_Version via
         the ``design_version_id`` foreign key.

Conventions (matching the designer/edc models):
  - UUID primary key.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column.
  - FK to ``study_versions`` by table name so the shared ORM registry resolves it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.study_version import StudyVersion
    from app.models.designer.visit import VisitDefinition


class SubjectPhaseType(enum.StrEnum):
    """Operational behavior of a configured subject phase."""

    registered = "registered"
    screen_failure = "screen_failure"
    common = "common"
    complete = "complete"
    arm = "arm"


class SubjectPhaseVisitDefinition(Base):
    """Ordered association between a subject phase and a protocol visit."""

    __tablename__ = "subject_phase_visit_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_phase_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subject_phase_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    visit_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "subject_phase_definition_id",
            "visit_definition_id",
            name="uq_subject_phase_visit",
        ),
        Index("ix_subject_phase_visit_phase_id", "subject_phase_definition_id"),
        Index("ix_subject_phase_visit_visit_id", "visit_definition_id"),
    )


class SubjectPhaseDefinition(Base):
    """A design-time subject phase definition bound to one ``Design_Version``.

    The ``name`` is unique within a single design version (``design_version_id``);
    the unique constraint below backs the service-level uniqueness check that
    returns the duplicate name on conflict (R3.2). ``display_order`` carries the
    1-999 ordering for presentation.
    """

    __tablename__ = "subject_phase_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (R3.3 — binds to exactly one design version)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Phase name — 1-100 characters, unique within the owning design version (R3.1, R3.2)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Controls visit association and operational subject behavior.
    phase_type: Mapped[SubjectPhaseType] = mapped_column(
        String(30),
        nullable=False,
        default=SubjectPhaseType.common,
        server_default=SubjectPhaseType.common.value,
    )

    # Presentation order — 1-999 (R3.1)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Relationship (resolved by string against the shared ORM registry)
    design_version: Mapped[StudyVersion] = relationship("StudyVersion", lazy="selectin")
    visits: Mapped[list[VisitDefinition]] = relationship(
        "VisitDefinition",
        secondary="subject_phase_visit_definitions",
        lazy="selectin",
        order_by="SubjectPhaseVisitDefinition.display_order",
    )

    @property
    def visit_definition_ids(self) -> list[uuid.UUID]:
        """Return linked protocol visits in their configured order."""
        return [visit.id for visit in self.visits]

    __table_args__ = (
        CheckConstraint(
            "phase_type IN ('registered', 'screen_failure', 'common', 'complete', 'arm')",
            name="ck_subject_phase_definition_type",
        ),
        UniqueConstraint(
            "design_version_id",
            "name",
            name="uq_subject_phase_definition_name_per_version",
        ),
        Index(
            "ix_subject_phase_definitions_design_version_id",
            "design_version_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SubjectPhaseDefinition(id={self.id}, "
            f"design_version_id={self.design_version_id}, name={self.name!r}, "
            f"phase_type={self.phase_type!r}, display_order={self.display_order})>"
        )
