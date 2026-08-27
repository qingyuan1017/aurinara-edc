"""Form data models — form instances (clinical data capture) and field values.

Hybrid storage: ``form_instances.data_jsonb`` stores the full payload for fast
retrieval; normalized ``field_values`` rows support audit, query, SDV, review,
and export per-field.

Satisfies Requirements:
  - 10.2: Form instance lifecycle statuses.
  - 22.3: Hybrid storage (JSONB + normalized rows).
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# JSONB on PostgreSQL; falls back to portable JSON on SQLite for unit tests.
JSONBType = JSONB().with_variant(JSON(), "sqlite")

# --- Enums ---


class FormInstanceStatus(enum.StrEnum):
    """Form instance lifecycle status (Requirement 10.2)."""

    not_started = "Not Started"
    in_progress = "In Progress"
    submitted = "Submitted"
    reviewed = "Reviewed"
    frozen = "Frozen"
    locked = "Locked"
    signed = "Signed"


# --- Models ---


class FormInstance(Base):
    """A clinical form occurrence for a subject, optionally tied to a visit.

    The ``data_jsonb`` column stores the full form payload for fast retrieval,
    while individual ``field_values`` rows provide per-field audit/query/SDV
    granularity (Requirement 22.3).
    """

    __tablename__ = "form_instances"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Subject this form instance belongs to
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    # Optional visit instance association
    visit_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("visit_instances.id", ondelete="SET NULL"),
        nullable=True,
        comment="Nullable — form may exist outside a visit context",
    )

    # Form definition this instance is based on
    form_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_definitions.id", ondelete="CASCADE"), nullable=False
    )

    # Lifecycle status
    status: Mapped[FormInstanceStatus] = mapped_column(
        String(20), nullable=False, default=FormInstanceStatus.not_started
    )

    # Hybrid storage — full JSON payload for fast read
    data_jsonb: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Submitted by
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    subject: Mapped["Subject"] = relationship("Subject", lazy="selectin")  # noqa: F821
    visit_instance: Mapped["VisitInstance | None"] = relationship(  # noqa: F821
        "VisitInstance", lazy="selectin"
    )
    form_definition: Mapped["FormDefinition"] = relationship(  # noqa: F821
        "FormDefinition", lazy="selectin"
    )
    submitter: Mapped["User | None"] = relationship(  # noqa: F821
        "User", lazy="selectin"
    )
    field_values: Mapped[list["FieldValue"]] = relationship(
        "FieldValue", back_populates="form_instance", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_form_instances_subject_id", "subject_id"),
        Index("ix_form_instances_visit_instance_id", "visit_instance_id"),
        Index("ix_form_instances_form_definition_id", "form_definition_id"),
        Index("ix_form_instances_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<FormInstance(id={self.id}, subject_id={self.subject_id}, "
            f"form_definition_id={self.form_definition_id}, status={self.status!r})>"
        )


class FieldValue(Base):
    """A single field value within a form instance (normalized storage).

    Each row represents the current value of one field, enabling per-field
    audit trails, queries, SDV, and review operations.
    """

    __tablename__ = "field_values"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning form instance
    form_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_instances.id", ondelete="CASCADE"), nullable=False
    )

    # Field definition reference
    field_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("field_definitions.id", ondelete="CASCADE"), nullable=False
    )

    # Serialized value
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Not-applicable marker (Requirement 10.6)
    is_not_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Last updater
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    form_instance: Mapped["FormInstance"] = relationship(
        "FormInstance", back_populates="field_values"
    )
    field_definition: Mapped["FieldDefinition"] = relationship(  # noqa: F821
        "FieldDefinition", lazy="selectin"
    )
    updater: Mapped["User | None"] = relationship(  # noqa: F821
        "User", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_field_values_form_instance_id", "form_instance_id"),
        Index("ix_field_values_field_definition_id", "field_definition_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<FieldValue(id={self.id}, form_instance_id={self.form_instance_id}, "
            f"field_definition_id={self.field_definition_id})>"
        )
