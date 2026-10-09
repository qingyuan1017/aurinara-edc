"""Form_Definition_Dependency model — a NEW Designer-owned design-time table.

A ``Form_Definition_Dependency`` is a typed, self-referential edge expressing
that one ``Form_Definition`` depends on another (for example a prerequisite form
that must be completed first). Both endpoints reference ``form_definitions`` and
the edge is self-guarded: a form cannot depend on itself (enforced by a DB CHECK
and the service layer).

Conventions (matching the designer models):
  - UUID primary key.
  - Timezone-aware ``created_at`` timestamp. Dependency edges are created or
    removed, not soft-deleted (matching association-table convention), so there
    is no ``deleted_at``.
  - FKs to ``form_definitions`` by table name so the shared ORM registry resolves
    them; both FKs cascade on delete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FormDefinitionDependency(Base):
    """A design-time form-to-form dependency edge (self-guarded)."""

    __tablename__ = "form_definition_dependencies"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # The dependent form and the form it depends on.
    form_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("form_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    depends_on_form_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("form_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Typed dependency; defaults to a prerequisite relationship.
    dependency_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="prerequisite",
        server_default="prerequisite",
        comment="e.g. prerequisite",
    )

    # Optional condition expression driving the dependency.
    condition_expression: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        CheckConstraint(
            "form_definition_id <> depends_on_form_definition_id",
            name="ck_form_dependency_not_self",
        ),
        UniqueConstraint(
            "form_definition_id",
            "depends_on_form_definition_id",
            "dependency_type",
            name="uq_form_dependency",
        ),
        Index(
            "ix_form_definition_dependencies_form_definition_id",
            "form_definition_id",
        ),
        Index(
            "ix_form_definition_dependencies_depends_on",
            "depends_on_form_definition_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FormDefinitionDependency(id={self.id}, "
            f"form_definition_id={self.form_definition_id}, "
            f"depends_on_form_definition_id={self.depends_on_form_definition_id}, "
            f"dependency_type={self.dependency_type!r})>"
        )
