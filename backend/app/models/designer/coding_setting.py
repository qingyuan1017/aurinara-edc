"""Coding_Setting model — a NEW Designer-owned design-time table.

A ``Coding_Setting`` describes how a coded item is medically/term coded: the
reference dictionary (e.g. MedDRA, WHODrug) and an optional coding rule. The
optional ``field_definition_id`` scopes the setting to the specific captured
field being coded; a null id carries a design-wide coding default. This is a
**new** designer table bound to exactly one ``Design_Version`` through
``design_version_id``.

Satisfies Requirements:
  - 4.8: Persist a coding setting (dictionary reference + rule) per coded item
         within a design version, bound to exactly one Design_Version.

Conventions (matching the designer models):
  - UUID primary key.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column.
  - FKs to ``study_versions`` / ``field_definitions`` by table name so the
    shared ORM registry resolves them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.form_metadata import FieldDefinition
    from app.models.designer.study_version import StudyVersion


class CodingSetting(Base):
    """A design-time coding setting bound to one Design_Version (R4.8)."""

    __tablename__ = "coding_settings"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (R4.8 — binds to exactly one design version)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional scoping to the specific coded field
    field_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("field_definitions.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Coding dictionary reference and optional rule (R4.8)
    dictionary_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    coding_rule: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    design_version: Mapped[StudyVersion] = relationship(
        "StudyVersion", lazy="selectin"
    )
    field_definition: Mapped[FieldDefinition | None] = relationship(
        "FieldDefinition", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_coding_settings_design_version_id",
            "design_version_id",
        ),
        Index(
            "ix_coding_settings_field_definition_id",
            "field_definition_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CodingSetting(id={self.id}, "
            f"design_version_id={self.design_version_id}, "
            f"dictionary_reference={self.dictionary_reference!r})>"
        )
