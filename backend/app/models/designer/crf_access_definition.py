"""Crf_Access_Definition model — a NEW Designer-owned design-time table.

A ``Crf_Access_Definition`` describes, for a single role, whether that role may
read and/or write a given form or field within a ``Draft_Design``. The optional
``form_definition_id`` / ``field_definition_id`` scope the grant: both null
means a design-wide default for the role, a form id scopes it to one form, and a
field id scopes it to one field. This is a **new** designer table bound to
exactly one ``Design_Version`` through ``design_version_id``.

Satisfies Requirements:
  - 4.6: Persist per-role read/write access for a form or field within a design
         version, bound to exactly one Design_Version.

Conventions (matching the designer models):
  - UUID primary key.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column.
  - FKs to ``study_versions`` / ``form_definitions`` / ``field_definitions`` by
    table name so the shared ORM registry resolves them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid a runtime import cycle; the registry resolves by string
    from app.models.designer.form_metadata import FieldDefinition, FormDefinition
    from app.models.designer.study_version import StudyVersion


class CrfAccessDefinition(Base):
    """A design-time per-role CRF read/write access grant (R4.6)."""

    __tablename__ = "crf_access_definitions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (R4.6 — binds to exactly one design version)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Role this access grant applies to
    role: Mapped[str] = mapped_column(String(100), nullable=False)

    # Optional scoping: a form, a field, or (both null) a design-wide default
    form_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("form_definitions.id", ondelete="CASCADE"),
        nullable=True,
    )
    field_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("field_definitions.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Read/write permissions (R4.6)
    can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
    form_definition: Mapped[FormDefinition | None] = relationship(
        "FormDefinition", lazy="selectin"
    )
    field_definition: Mapped[FieldDefinition | None] = relationship(
        "FieldDefinition", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_crf_access_definitions_design_version_id",
            "design_version_id",
        ),
        Index(
            "ix_crf_access_definitions_form_definition_id",
            "form_definition_id",
        ),
        Index(
            "ix_crf_access_definitions_field_definition_id",
            "field_definition_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CrfAccessDefinition(id={self.id}, "
            f"design_version_id={self.design_version_id}, role={self.role!r}, "
            f"can_read={self.can_read}, can_write={self.can_write})>"
        )
