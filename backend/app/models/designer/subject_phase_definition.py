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

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
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

    # Presentation order — 1-999 (R3.1)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Relationship (resolved by string against the shared ORM registry)
    design_version: Mapped[StudyVersion] = relationship(
        "StudyVersion", lazy="selectin"
    )

    __table_args__ = (
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
            f"display_order={self.display_order})>"
        )
