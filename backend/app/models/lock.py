"""FreezeLock model — freeze and lock controls across the object hierarchy.

Satisfies Requirements:
  - 16.1: Freeze state applied at field, form, visit, subject, site, or study level.
  - 16.2: Lock state applied at field, form, visit, subject, site, or study level.
  - 16.4: Unlock requires a reason and clears the lock state.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
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

# --- Enums ---


class FreezeLockObjectType(enum.StrEnum):
    """Allowed object types for freeze/lock (Requirement 16.1, 16.2)."""

    field = "field"
    form = "form"
    visit = "visit"
    subject = "subject"
    site = "site"
    study = "study"


class FreezeLockType(enum.StrEnum):
    """Type of lock: freeze or hard lock."""

    freeze = "freeze"
    lock = "lock"


# --- Models ---


class FreezeLock(Base):
    """A freeze or lock record applied to a clinical object.

    Supports the object hierarchy field → form → visit → subject → site → study.
    When is_active is True the object is currently frozen/locked.
    Unlocking sets is_active to False and requires unlock_reason (Requirement 16.4).
    """

    __tablename__ = "freezes_locks"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Target object (polymorphic reference)
    object_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="One of: field, form, visit, subject, site, study",
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        comment="ID of the target object",
    )

    # Lock type
    lock_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="One of: freeze, lock",
    )

    # Active state
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="True while the freeze/lock is in effect",
    )

    # Who locked and when
    locked_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Unlock tracking (populated on unlock — Requirement 16.4)
    unlocked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    unlocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unlock_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Required when unlocking (Requirement 16.4)",
    )

    # Record creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    locker: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[locked_by], lazy="selectin"
    )
    unlocker: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[unlocked_by], lazy="selectin"
    )

    __table_args__ = (
        Index("ix_freezes_locks_object_type_object_id", "object_type", "object_id"),
        Index("ix_freezes_locks_lock_type", "lock_type"),
        Index("ix_freezes_locks_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<FreezeLock(id={self.id}, object_type={self.object_type!r}, "
            f"object_id={self.object_id}, lock_type={self.lock_type!r}, "
            f"is_active={self.is_active})>"
        )
