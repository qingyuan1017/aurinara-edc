"""File attachment metadata and soft-delete state.

The file bytes live in configured object storage; this model stores the
metadata needed to locate and authorize the object.  The parent reference is
polymorphic because attachments may belong to different clinical object
levels.  Deleting an attachment is logical only so its history remains
available for audit and retention requirements.

Satisfies Requirements:
  - 27.1: Persists uploaded-file metadata linked to a clinical object.
  - 27.3: Soft-deletes attachments with actor, timestamp, and reason.
  - 22.6: Uses UUID keys, UTC timestamps, and filter indexes.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FileAttachmentObjectType(enum.StrEnum):
    """Parent object levels supported by the shared file primitive."""

    field = "field"
    form = "form"
    visit = "visit"
    subject = "subject"
    site = "site"
    study = "study"
    operational = "operational"


class FileAttachmentModule(enum.StrEnum):
    """Content authority for a shared stored file."""

    EDC = "EDC"
    CTMS = "CTMS"


class FileAttachment(Base):
    """Metadata for a file stored in S3 or local object storage.

    ``object_type`` and ``object_id`` form the polymorphic parent reference.
    The denormalized study/site/subject scope columns support authorization and
    efficient scoped queries without requiring the storage service to load the
    parent object first.
    """

    __tablename__ = "file_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    module: Mapped[str] = mapped_column(
        String(20), nullable=False, default="EDC", server_default="EDC"
    )
    attachment_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="Clinical_Attachment", server_default="Clinical_Attachment"
    )

    # Polymorphic parent reference.
    object_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Parent clinical object type (field, form, visit, subject, site, or study)",
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        comment="ID of the parent clinical object",
    )

    # Authorization and query scope.
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="CASCADE"), nullable=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True
    )

    # Stored object metadata.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(
        Text, nullable=False, comment="S3 or local object-storage key"
    )

    # Upload provenance.
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Soft deletion (Requirement 27.3); the row and storage metadata are retained.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    delete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # CTMS traceability and retention metadata.  These fields are nullable for
    # pre-CTMS EDC rows and are populated for every operational attachment.
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active", server_default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships use explicit foreign-key lists because User is referenced
    # by both uploaded_by and deleted_by.
    study: Mapped["Study"] = relationship("Study", lazy="selectin")  # noqa: F821
    site: Mapped["Site | None"] = relationship("Site", lazy="selectin")  # noqa: F821
    subject: Mapped["Subject | None"] = relationship("Subject", lazy="selectin")  # noqa: F821
    uploader: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[uploaded_by], lazy="selectin"
    )
    deleter: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[deleted_by], lazy="selectin"
    )

    __table_args__ = (
        Index("ix_file_attachments_object_type_object_id", "object_type", "object_id"),
        Index("ix_file_attachments_study_id", "study_id"),
        Index("ix_file_attachments_site_id", "site_id"),
        Index("ix_file_attachments_subject_id", "subject_id"),
        Index("ix_file_attachments_uploaded_by", "uploaded_by"),
        Index("ix_file_attachments_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<FileAttachment(id={self.id}, object_type={self.object_type!r}, "
            f"object_id={self.object_id}, filename={self.filename!r})>"
        )
