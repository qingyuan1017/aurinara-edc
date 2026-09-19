"""Notification model for clinical workflow events.

Satisfies Requirements:
  - 28.4: Supports Unread, Read, and Archived notification statuses.
  - 22.6: Indexed for efficient recipient/status querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# JSONB on PostgreSQL; use portable JSON for SQLite-backed unit tests.
JSONBType = JSONB().with_variant(JSON(), "sqlite")


class NotificationStatus(enum.StrEnum):
    """Notification lifecycle status (Requirement 28.4)."""

    unread = "Unread"
    read = "Read"
    archived = "Archived"


class Notification(Base):
    """A notification addressed to one user.

    Workflow services create notifications with a type and payload describing
    the event. The payload remains flexible so each event can include the
    relevant clinical or operational references without schema changes.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="User receiving the notification",
    )
    module: Mapped[str] = mapped_column(
        String(20), nullable=False, default="EDC", server_default="EDC"
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Workflow event type, such as query_assigned or export_completed",
    )
    payload_json: Mapped[dict] = mapped_column(
        JSONBType,
        nullable=False,
        default=dict,
        comment="Event-specific notification payload",
    )
    status: Mapped[NotificationStatus] = mapped_column(
        String(20),
        nullable=False,
        default=NotificationStatus.unread,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active", server_default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821

    __table_args__ = (
        Index("ix_notifications_user_status", "user_id", "status"),
        Index("ix_notifications_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, user_id={self.user_id}, "
            f"type={self.type!r}, status={self.status!r})>"
        )
