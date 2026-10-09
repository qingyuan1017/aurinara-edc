"""Visit_Definition_Dependency model — a NEW Designer-owned design-time table.

A ``Visit_Definition_Dependency`` is a typed, self-referential edge expressing
that one ``Visit_Definition`` depends on another. Because a cycle is now a visit
(``visit_type == 'cycle'``), this single table expresses visit→visit,
cycle→visit, visit→cycle, and cycle→cycle dependencies — including the
``'cycle_member'`` edges migrated from the former ``cycle_definition_visits``
membership. The edge is self-guarded: a visit cannot depend on itself (enforced
by a DB CHECK and the service layer).

Conventions (matching the designer models):
  - UUID primary key.
  - Timezone-aware ``created_at`` timestamp. Dependency edges are created or
    removed, not soft-deleted, so there is no ``deleted_at``.
  - FKs to ``visit_definitions`` by table name so the shared ORM registry
    resolves them; both FKs cascade on delete.
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


class VisitDefinitionDependency(Base):
    """A design-time visit-to-visit dependency edge (self-guarded)."""

    __tablename__ = "visit_definition_dependencies"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # The dependent visit and the visit it depends on.
    visit_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    depends_on_visit_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Typed dependency; defaults to a prerequisite relationship. The migration
    # writes ``'cycle_member'`` edges here to preserve old cycle membership.
    dependency_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="prerequisite",
        server_default="prerequisite",
        comment="e.g. prerequisite, cycle_member",
    )

    # Optional condition expression driving the dependency.
    condition_expression: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        CheckConstraint(
            "visit_definition_id <> depends_on_visit_definition_id",
            name="ck_visit_dependency_not_self",
        ),
        UniqueConstraint(
            "visit_definition_id",
            "depends_on_visit_definition_id",
            "dependency_type",
            name="uq_visit_dependency",
        ),
        Index(
            "ix_visit_definition_dependencies_visit_definition_id",
            "visit_definition_id",
        ),
        Index(
            "ix_visit_definition_dependencies_depends_on",
            "depends_on_visit_definition_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VisitDefinitionDependency(id={self.id}, "
            f"visit_definition_id={self.visit_definition_id}, "
            f"depends_on_visit_definition_id={self.depends_on_visit_definition_id}, "
            f"dependency_type={self.dependency_type!r})>"
        )
