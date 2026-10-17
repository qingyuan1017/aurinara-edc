"""Codelist models — controlled vocabularies owned by the Designer module.

Codelists (``Codelist``) and their items (``CodelistItem``) are design-time
Designer_Definitions: controlled vocabularies referenced by field definitions
within a ``Design_Version`` (R6). They were reassigned here out of the combined
EDC ``form_metadata`` module.

The move is a **code-layer ownership change only** — the backing tables
(``codelists`` and ``codelist_items``) and all their columns are unchanged, so
stored values are preserved and the migration is purely additive (R11.1). Each
``Codelist`` binds to exactly one ``Design_Version`` via its FK to
``study_versions`` (R6.4).

Satisfies Requirements:
  - 6.1: Codelists with a name and 1-1000 items persisted within a Draft_Design.
  - 6.4: Each Codelist associates with exactly one Design_Version (FK).
  - 11.1: Ownership reassignment with no table/column renames.
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.odm_oid import new_odm_oid

if TYPE_CHECKING:  # avoid runtime import cycles; resolved via the shared registry
    from app.models.designer.study_version import StudyVersion


class Codelist(Base):
    """A reusable controlled vocabulary within a Design_Version (R6.1, R6.4)."""

    __tablename__ = "codelists"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning study version (the Design_Version this codelist binds to — R6.4)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )
    odm_oid: Mapped[str] = mapped_column(
        String(255), nullable=False, default=lambda: new_odm_oid("CL")
    )

    # Code list metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    study_version: Mapped[StudyVersion] = relationship(
        "StudyVersion", lazy="selectin"
    )
    items: Mapped[list[CodelistItem]] = relationship(
        "CodelistItem", back_populates="codelist", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_codelists_study_version_id", "study_version_id"),
    )

    def __repr__(self) -> str:
        return f"<Codelist(id={self.id}, code={self.code!r}, name={self.name!r})>"


class CodelistItem(Base):
    """A single entry within a code list (R6.1).

    Carries optional normal_low/normal_high reference-range bounds for use by
    lab abnormality edit checks.
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
    specify: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Lab reference ranges (nullable)
    normal_low: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    normal_high: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # Relationships
    codelist: Mapped[Codelist] = relationship(
        "Codelist", back_populates="items"
    )

    __table_args__ = (
        Index("ix_codelist_items_codelist_id", "codelist_id"),
    )

    def __repr__(self) -> str:
        return f"<CodelistItem(id={self.id}, code={self.code!r}, label={self.label!r})>"
