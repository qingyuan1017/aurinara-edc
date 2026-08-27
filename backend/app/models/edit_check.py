"""EditCheck and ValidationResult models — declarative edit check rules and their results.

Satisfies Requirements:
  - 12.1: Rule validated against operator/condition schema before persisting.
  - 12.6: Edit checks versioned with their owning Study_Version.
  - 22.6: Indexed for efficient querying.
"""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EditCheck(Base):
    """A declarative edit check rule versioned with its owning Study_Version.

    Rules use a constrained JSON DSL (boolean trees of and/or/not over conditions).
    The engine never executes user-provided code (Requirement 12.7).
    """

    __tablename__ = "edit_checks"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning study version (Requirement 12.6)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Descriptive metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Declarative JSON DSL rule definition (Requirement 12.1)
    rule_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Declarative JSON DSL rule definition (boolean tree of conditions)",
    )

    # Severity level (Requirement 12.3)
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="One of: info, warning, error, query",
    )

    # Active flag
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    study_version: Mapped["StudyVersion"] = relationship(  # noqa: F821
        "StudyVersion", lazy="selectin"
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(
        "ValidationResult", back_populates="edit_check", lazy="noload"
    )

    __table_args__ = (
        Index("ix_edit_checks_study_version_id", "study_version_id"),
        Index("ix_edit_checks_severity", "severity"),
        Index("ix_edit_checks_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<EditCheck(id={self.id}, name={self.name!r}, "
            f"severity={self.severity!r}, is_active={self.is_active})>"
        )


class ValidationResult(Base):
    """A result produced when an edit check fires against a form instance.

    Records the specific rule violation with severity, message, and resolution state.
    """

    __tablename__ = "validation_results"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning edit check
    edit_check_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("edit_checks.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Target form instance
    form_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("form_instances.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Severity (copied from edit check at evaluation time)
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="One of: info, warning, error, query",
    )

    # Human-readable violation message
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Resolution tracking
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    edit_check: Mapped["EditCheck"] = relationship(
        "EditCheck", back_populates="validation_results", lazy="selectin"
    )
    form_instance: Mapped["FormInstance"] = relationship(  # noqa: F821
        "FormInstance", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_validation_results_edit_check_id", "edit_check_id"),
        Index("ix_validation_results_form_instance_id", "form_instance_id"),
        Index("ix_validation_results_is_resolved", "is_resolved"),
    )

    def __repr__(self) -> str:
        return (
            f"<ValidationResult(id={self.id}, edit_check_id={self.edit_check_id}, "
            f"severity={self.severity!r}, is_resolved={self.is_resolved})>"
        )
