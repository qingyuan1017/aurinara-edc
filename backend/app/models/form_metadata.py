"""Form metadata models — eCRF definitions, sections, fields, and code lists.

Form versioning is achieved through the ``study_version_id`` relationship on
``form_definitions``; there is **no separate ``form_versions`` table**. A form's
version is the version of its owning Study_Version (Requirement 9.5, 5.5).

Satisfies Requirements:
  - 9.1: Form definitions within a study version (name, form code, display order,
          repeating flag).
  - 9.2: Form sections and field definitions, ordered for display.
  - 9.5: Code lists and code list items referenced by fields.
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

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

# JSONB on PostgreSQL; falls back to a portable JSON type on SQLite so that
# Base.metadata.create_all works for SQLite-backed unit tests.
JSONBType = JSONB().with_variant(JSON(), "sqlite")

# --- Models ---


class FormDefinition(Base):
    """An eCRF form definition belonging to a Study_Version (Requirement 9.1).

    The owning Study_Version *is* the form's version — there is no separate
    form_versions table. Form definitions are immutable once the owning version
    is published.
    """

    __tablename__ = "form_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning study version (a form's version is its owning study version)
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
    study_version: Mapped["StudyVersion"] = relationship(  # noqa: F821
        "StudyVersion", lazy="selectin"
    )
    sections: Mapped[list["FormSection"]] = relationship(
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
    """A logical grouping of fields within a form definition (Requirement 9.2)."""

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
    form_definition: Mapped["FormDefinition"] = relationship(
        "FormDefinition", back_populates="sections"
    )
    fields: Mapped[list["FieldDefinition"]] = relationship(
        "FieldDefinition", back_populates="form_section", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_form_sections_form_definition_id", "form_definition_id"),
    )

    def __repr__(self) -> str:
        return f"<FormSection(id={self.id}, name={self.name!r})>"


class FieldDefinition(Base):
    """A field within a form section (Requirements 9.2, 9.3, 9.4)."""

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

    # Code list reference (nullable)
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
    form_section: Mapped["FormSection"] = relationship(
        "FormSection", back_populates="fields"
    )
    codelist: Mapped["Codelist | None"] = relationship(
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


class Codelist(Base):
    """A reusable list of coded values within a Study_Version (Requirement 9.5)."""

    __tablename__ = "codelists"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning study version
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )

    # Code list metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    study_version: Mapped["StudyVersion"] = relationship(  # noqa: F821
        "StudyVersion", lazy="selectin"
    )
    items: Mapped[list["CodelistItem"]] = relationship(
        "CodelistItem", back_populates="codelist", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_codelists_study_version_id", "study_version_id"),
    )

    def __repr__(self) -> str:
        return f"<Codelist(id={self.id}, code={self.code!r}, name={self.name!r})>"


class CodelistItem(Base):
    """A single entry within a code list (Requirement 9.5).

    Carries optional normal_low/normal_high reference-range bounds for use by
    lab abnormality edit checks (Requirement 12 lab abnormality support).
    """

    __tablename__ = "codelist_items"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning code list
    codelist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("codelists.id", ondelete="CASCADE"), nullable=False
    )

    # Item metadata
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # Lab reference ranges (nullable)
    normal_low: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    normal_high: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # Relationships
    codelist: Mapped["Codelist"] = relationship(
        "Codelist", back_populates="items"
    )

    __table_args__ = (
        Index("ix_codelist_items_codelist_id", "codelist_id"),
    )

    def __repr__(self) -> str:
        return f"<CodelistItem(id={self.id}, code={self.code!r}, label={self.label!r})>"
