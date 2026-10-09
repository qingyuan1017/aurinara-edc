"""Cycle_Definition model — a NEW Designer-owned design-time table.

A ``Cycle_Definition`` describes a repeating group of visits authored inside a
``Draft_Design`` (for example a treatment cycle that recurs across a protocol).
This is a **new** designer table (not a reassignment of an existing EDC table),
bound to exactly one ``Design_Version`` through ``study_version_id`` and holding
a many-to-many membership of ``Visit_Definition`` records.

Satisfies Requirements:
  - 4.4: Persist the Cycle_Definition and its member Visit_Definitions within a
         Draft_Design.

Conventions (matching the designer/edc models):
  - UUID primary key.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column.
  - FK to ``study_versions`` by table name so the shared ORM registry resolves it.
  - Membership references ``visit_definitions`` by table/class name so the shared
    ORM registry resolves ``VisitDefinition`` regardless of which module module
    currently owns it (the model is being moved to ``app.models.designer.visit``
    by a concurrent task); no runtime import of ``VisitDefinition`` is taken.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.study_version import StudyVersion

# Association table for the Cycle_Definition <-> Visit_Definition membership
# (R4.4). Columns reference tables by name so the shared ORM registry resolves
# ``visit_definitions`` independent of which module owns the VisitDefinition
# model at import time.
cycle_definition_visits = Table(
    "cycle_definition_visits",
    Base.metadata,
    Column(
        "cycle_definition_id",
        Uuid,
        ForeignKey("cycle_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "visit_definition_id",
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class CycleDefinition(Base):
    """A design-time cycle definition bound to one ``Design_Version``.

    The ``name`` is unique within a single design version (``study_version_id``);
    the unique constraint below backs the service-level uniqueness check.
    ``display_order`` carries the ordering for presentation. The ``visits``
    relationship captures the cycle's member Visit_Definitions (R4.4) through the
    ``cycle_definition_visits`` association table, referenced by string against
    the shared ORM registry.
    """

    __tablename__ = "cycle_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (binds to exactly one design version)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Cycle name — 1-100 characters, unique within the owning design version
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Presentation order
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

    # Relationships (resolved by string against the shared ORM registry)
    study_version: Mapped[StudyVersion] = relationship(
        "StudyVersion", lazy="selectin"
    )
    # Many-to-many membership to Visit_Definitions (R4.4). Resolved by class name
    # so the registry links regardless of the owning module of VisitDefinition.
    visits = relationship(
        "VisitDefinition",
        secondary=cycle_definition_visits,
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "study_version_id",
            "name",
            name="uq_cycle_definition_name_per_version",
        ),
        Index(
            "ix_cycle_definitions_study_version_id",
            "study_version_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CycleDefinition(id={self.id}, "
            f"study_version_id={self.study_version_id}, name={self.name!r}, "
            f"display_order={self.display_order})>"
        )
