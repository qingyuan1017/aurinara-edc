"""Form record model — repeating records within a form instance.

Each repeating form instance can contain multiple records, each identified
by a monotonically assigned sequence number (per form_instance). Records
support soft-delete with actor, timestamp, and reason for traceability.

Satisfies Requirements:
  - 11.1: Add record with monotonic sequence number.
  - 11.3: Soft-delete with actor, timestamp, reason; row retained.
  - 22.2: Soft-delete retention (no physical removal).
  - 22.6: Indexed for efficient querying.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# JSONB on PostgreSQL; falls back to portable JSON on SQLite for unit tests.
JSONBType = JSONB().with_variant(JSON(), "sqlite")


class FormRecord(Base):
    """A single record (row) within a repeating form instance.

    Sequence numbers are monotonically assigned per form_instance (not globally
    unique). Soft-delete retains the row with deletion metadata for traceability
    (Requirement 11.3, 22.2).
    """

    __tablename__ = "form_records"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning form instance
    form_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_instances.id", ondelete="CASCADE"), nullable=False
    )

    # Monotonically assigned sequence number per form_instance (Requirement 11.1)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Row field values stored as JSON (nullable — may not have data yet)
    data_jsonb: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    # Soft-delete columns (Requirement 11.3, 22.2)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    form_instance: Mapped["FormInstance"] = relationship(  # noqa: F821
        "FormInstance", lazy="selectin"
    )
    deleter: Mapped["User | None"] = relationship(  # noqa: F821
        "User", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_form_records_form_instance_id", "form_instance_id"),
        Index(
            "ix_form_records_form_instance_sequence",
            "form_instance_id",
            "sequence_number",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FormRecord(id={self.id}, form_instance_id={self.form_instance_id}, "
            f"sequence_number={self.sequence_number})>"
        )
