"""Export model — export job tracking for clinical data exports.

Tracks the lifecycle of export jobs: Queued → Running → Completed/Failed.

Satisfies Requirements:
  - 19.1: Export job creation and status tracking (Queued → Running → Completed/Failed).
  - 19.2: Subject list export support.
  - 19.3: Filters: site, subject, visit, form, domain, date_range, changed_since,
           locked_only, clean_only.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
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


class ExportStatus(enum.StrEnum):
    """Export job lifecycle status (Requirement 19.1)."""

    queued = "Queued"
    running = "Running"
    completed = "Completed"
    failed = "Failed"


class ExportType(enum.StrEnum):
    """Export format types (Requirements 19.1, 19.2)."""

    csv = "csv"
    subject_list = "subject_list"


# --- Model ---


class Export(Base):
    """An export job tracking record.

    Stores the export job metadata, filter parameters, and resulting file
    information. Status transitions: Queued → Running → Completed/Failed.
    """

    __tablename__ = "exports"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Study this export belongs to
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )

    # Export type (csv, subject_list, etc.)
    export_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ExportType.csv
    )

    # Job status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExportStatus.queued
    )

    # Filter parameters (JSON): site, subject, visit, form, domain,
    # date_range, changed_since, locked_only, clean_only
    filters: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    # Generated file information
    file_path: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Path/key to the generated file (S3 or local)"
    )
    file_size: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="File size in bytes"
    )

    # Error information (set on failure)
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message set on failure"
    )

    # Requesting user
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    study: Mapped["Study"] = relationship("Study", lazy="selectin")  # noqa: F821
    requester: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821

    __table_args__ = (
        Index("ix_exports_study_id", "study_id"),
        Index("ix_exports_status", "status"),
        Index("ix_exports_requested_by", "requested_by"),
    )

    def __repr__(self) -> str:
        return (
            f"<Export(id={self.id}, study_id={self.study_id}, "
            f"export_type={self.export_type!r}, status={self.status!r})>"
        )
