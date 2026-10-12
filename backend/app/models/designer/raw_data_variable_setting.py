"""Raw_Data_Variable_Setting model — a NEW Designer-owned design-time table.

A ``Raw_Data_Variable_Setting`` describes a captured raw-data variable: its
name, its data type, and a free-form ``attributes`` JSON bag for any
type-specific metadata (length, format, controlled terminology, etc.). This is
a **new** designer table bound to exactly one ``Design_Version`` through
``design_version_id``.

Satisfies Requirements:
  - 4.7: Persist a raw-data variable setting (name, type, attributes) per
         captured item within a design version, bound to exactly one
         Design_Version.

Conventions (matching the designer models):
  - UUID primary key.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column.
  - FK to ``study_versions`` by table name so the shared ORM registry resolves it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.designer.form_metadata import JSONBType

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.form_metadata import FieldDefinition
    from app.models.designer.study_version import StudyVersion


class RawDataVariableSetting(Base):
    """A design-time raw-data variable setting bound to one Design_Version (R4.7)."""

    __tablename__ = "raw_data_variable_settings"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (R4.7 — binds to exactly one design version)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional field binding. Legacy/free-form variables remain unbound, while
    # generated form-dataset variables use one configuration row per field.
    field_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("field_definitions.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )

    # Variable identity and type (R4.7)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Dataset-generation configuration: a display label for a fixed variable and
    # a suffix applied for special variable types. Both optional and nullable.
    label: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="display label for a fixed variable"
    )
    suffix: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="suffix for special variable types"
    )
    year_suffix: Mapped[str | None] = mapped_column(String(50), nullable=True)
    month_suffix: Mapped[str | None] = mapped_column(String(50), nullable=True)
    day_suffix: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Free-form, type-specific attributes (R4.7)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)

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
    field_definition: Mapped[FieldDefinition | None] = relationship(
        "FieldDefinition", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_raw_data_variable_settings_design_version_id",
            "design_version_id",
        ),
        Index(
            "ix_raw_data_variable_settings_field_definition_id",
            "field_definition_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RawDataVariableSetting(id={self.id}, "
            f"design_version_id={self.design_version_id}, name={self.name!r}, "
            f"data_type={self.data_type!r})>"
        )
