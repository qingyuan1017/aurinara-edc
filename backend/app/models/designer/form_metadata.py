"""Designer-owned CRF form metadata — form, section, and field definitions.

These design-time artifacts were reassigned from the EDC module to the Designer
module as part of the Designer / EDC refactor. ``FormDefinition``,
``FormSection``, and ``FieldDefinition`` are Designer_Definitions: they describe
the structure of an eCRF and belong to a ``Design_Version`` (``study_versions``).

The move is a **code-layer ownership change only** — the backing tables
(``form_definitions``, ``form_sections``, ``field_definitions``) and all columns
are unchanged, so stored values are preserved and the migration is purely
additive (R11.1). The FK to ``study_versions`` is kept intact.

``Codelist`` / ``CodelistItem`` are owned by ``app.models.designer.codelist``.
The ``field_definitions.codelist_id`` FK and the ``FieldDefinition.codelist``
relationship reference ``Codelist`` by table/class name and resolve through the
shared ORM registry.

Satisfies Requirements:
  - 4.1: Form definitions mapped to a Design_Version (name, form code, display
          order, repeating flag).
  - 4.2: Form sections and field definitions, ordered for display.
  - 11.1: Ownership reassignment with no table/column renames (stored values
          preserved); FK to ``study_versions`` kept.
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid runtime import cycles across module boundaries
    from app.models.designer.codelist import Codelist
    from app.models.designer.study_version import StudyVersion

# JSONB on PostgreSQL; falls back to a portable JSON type on SQLite so that
# Base.metadata.create_all works for SQLite-backed unit tests.
JSONBType = JSONB().with_variant(JSON(), "sqlite")

# --- Models ---


class FormDefinition(Base):
    """An eCRF form definition belonging to a Design_Version (Requirement 4.1).

    The owning Design_Version (``study_versions`` row) *is* the form's version —
    there is no separate form_versions table. Form definitions are immutable once
    the owning version is published.
    """

    __tablename__ = "form_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (a form's version is its owning study version)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )

    # Form metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    form_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='e.g. "AE", "CM", "DM"'
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_repeating: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    study_version: Mapped[StudyVersion] = relationship(
        "StudyVersion", lazy="selectin"
    )
    sections: Mapped[list[FormSection]] = relationship(
        "FormSection", back_populates="form_definition", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_form_definitions_study_version_id", "study_version_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<FormDefinition(id={self.id}, form_code={self.form_code!r}, "
            f"name={self.name!r})>"
        )


class FormSection(Base):
    """A logical grouping of fields within a form definition (Requirement 4.2)."""

    __tablename__ = "form_sections"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning form definition
    form_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_definitions.id", ondelete="CASCADE"), nullable=False
    )

    # Section metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    form_definition: Mapped[FormDefinition] = relationship(
        "FormDefinition", back_populates="sections"
    )
    fields: Mapped[list[FieldDefinition]] = relationship(
        "FieldDefinition", back_populates="form_section", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_form_sections_form_definition_id", "form_definition_id"),
    )

    def __repr__(self) -> str:
        return f"<FormSection(id={self.id}, name={self.name!r})>"


class FieldDefinition(Base):
    """A field within a form section (Requirements 4.2).

    References an optional ``Codelist`` which remains EDC-owned for now (split
    into the Designer codelist module by a separate task); the relationship is
    resolved by name through the shared ORM registry.
    """

    __tablename__ = "field_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning form section
    form_section_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_sections.id", ondelete="CASCADE"), nullable=False
    )

    # Identity / presentation
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    variable_name: Mapped[str] = mapped_column(String(255), nullable=False)
    control_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment=(
            "text, textarea, integer, decimal, date, datetime, time, radio, "
            "checkbox, dropdown, multi-select, boolean, file_upload, calculated, "
            "repeating_table, coded_term"
        ),
    )
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Code list reference (nullable) — ``codelists`` remains EDC-owned for now
    codelist_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("codelists.id", ondelete="SET NULL"), nullable=True
    )

    # Optional attributes
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decimal_precision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regex_validation: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility_rule: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    # Behaviour flags
    is_read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_calculated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    calculation_expression: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ordering
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    form_section: Mapped[FormSection] = relationship(
        "FormSection", back_populates="fields"
    )
    codelist: Mapped[Codelist | None] = relationship(
        "Codelist", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_field_definitions_form_section_id", "form_section_id"),
        Index("ix_field_definitions_codelist_id", "codelist_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<FieldDefinition(id={self.id}, variable_name={self.variable_name!r}, "
            f"control_type={self.control_type!r})>"
        )


__all__ = [
    "FieldDefinition",
    "FormDefinition",
    "FormSection",
    "JSONBType",
]
