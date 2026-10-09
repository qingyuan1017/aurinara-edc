"""Arm_Definition model — a NEW Designer-owned design-time table.

An ``Arm_Definition`` describes a study arm or treatment group authored inside a
``Draft_Design``. This is a **new** designer table (not a reassignment of an
existing EDC table), bound to exactly one ``Design_Version`` through
``study_version_id``.

Satisfies Requirements:
  - 4.5: Persist the Arm_Definition within a Draft_Design.

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
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.study_version import StudyVersion


class ArmDefinition(Base):
    """A design-time arm/treatment-group definition bound to one ``Design_Version``.

    The ``name`` is unique within a single design version (``study_version_id``);
    the unique constraint below backs the service-level uniqueness check.
    ``display_order`` carries the ordering for presentation and ``description``
    is an optional free-text description of the arm.
    """

    __tablename__ = "arm_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (binds to exactly one design version)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Arm name — 1-100 characters, unique within the owning design version
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Presentation order
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Optional free-text description of the arm/treatment group
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    study_version: Mapped[StudyVersion] = relationship(
        "StudyVersion", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            "study_version_id",
            "name",
            name="uq_arm_definition_name_per_version",
        ),
        Index(
            "ix_arm_definitions_study_version_id",
            "study_version_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ArmDefinition(id={self.id}, "
            f"study_version_id={self.study_version_id}, name={self.name!r}, "
            f"display_order={self.display_order})>"
        )
