"""Query and QueryMessage models — clinical data queries and threaded responses.

Satisfies Requirements:
  - 13.1: Query linked to exactly one affected object (target_type + target_id).
  - 13.6: Complete threaded message history (append-only query_messages).
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

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

# --- Enums ---


class QueryStatus(enum.StrEnum):
    """Query lifecycle status (Requirement 13.2)."""

    open = "Open"
    answered = "Answered"
    closed = "Closed"
    reopened = "Reopened"
    cancelled = "Cancelled"


class QueryTargetType(enum.StrEnum):
    """Allowed target types for a query (Requirement 13.1).

    A query targets exactly one affected object.
    """

    subject = "Subject"
    visit_instance = "Visit_Instance"
    form_instance = "Form_Instance"
    form_record = "Form_Record"
    field = "Field"


class QueryType(enum.StrEnum):
    """Origin of the query — manual or system-generated."""

    manual = "manual"
    system = "system"


# --- Models ---


class Query(Base):
    """A clinical data query linked to exactly one affected object.

    Queries follow the lifecycle: Open → Answered → Closed (or Cancelled),
    with reopen support (Requirement 13.2).
    """

    __tablename__ = "queries"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Study context
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )

    # Optional site context
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )

    # Optional subject context
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )

    # Exactly-one affected object (Requirement 13.1)
    target_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="One of: Subject, Visit_Instance, Form_Instance, Form_Record, Field",
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        comment="ID of the affected object",
    )

    # Initial query description
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Query origin
    query_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default=QueryType.manual
    )

    # Optional notification assignment target (Requirement 28.1)
    assigned_role: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Role whose in-scope active users receive assignment notifications",
    )

    # Lifecycle status
    status: Mapped[QueryStatus] = mapped_column(
        String(20), nullable=False, default=QueryStatus.open
    )

    # Ownership
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Closure tracking
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    study: Mapped["Study"] = relationship("Study", lazy="selectin")  # noqa: F821
    site: Mapped["Site | None"] = relationship("Site", lazy="selectin")  # noqa: F821
    subject: Mapped["Subject | None"] = relationship(  # noqa: F821
        "Subject", lazy="selectin"
    )
    creator: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[created_by], lazy="selectin"
    )
    closer: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[closed_by], lazy="selectin"
    )
    messages: Mapped[list["QueryMessage"]] = relationship(
        "QueryMessage", back_populates="query", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_queries_study_id", "study_id"),
        Index("ix_queries_target_type_target_id", "target_type", "target_id"),
        Index("ix_queries_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Query(id={self.id}, study_id={self.study_id}, "
            f"target_type={self.target_type!r}, status={self.status!r})>"
        )


class QueryMessage(Base):
    """An append-only message in a query thread (Requirement 13.6).

    Messages are never updated or deleted — the thread is immutable once written.
    """

    __tablename__ = "query_messages"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning query
    query_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("queries.id", ondelete="CASCADE"), nullable=False
    )

    # Author
    author_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Message content
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    query: Mapped["Query"] = relationship("Query", back_populates="messages")
    author: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821

    __table_args__ = (Index("ix_query_messages_query_id", "query_id"),)

    def __repr__(self) -> str:
        return (
            f"<QueryMessage(id={self.id}, query_id={self.query_id}, "
            f"author_id={self.author_id})>"
        )
