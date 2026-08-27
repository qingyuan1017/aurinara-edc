"""Review status model — tracks clinical review state per form instance.

Satisfies Requirements:
  - 15.1: Mark form instances as reviewed with actor/timestamp.
  - 22.6: Indexed for efficient querying.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReviewStatus(Base):
    """Tracks whether a form instance has been reviewed.

    One row per form_instance (unique constraint). The reviewed_by and
    reviewed_at fields record who performed the review and when.
    """

    __tablename__ = "review_status"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # The form instance being reviewed (one review status per form instance)
    form_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_instances.id", ondelete="CASCADE"), nullable=False
    )

    # Review state
    is_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Who performed the review (nullable until actually reviewed)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # When the review was performed
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    reviewer: Mapped["User | None"] = relationship(  # noqa: F821
        "User", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("form_instance_id", name="uq_review_status_form_instance_id"),
        Index("ix_review_status_form_instance_id", "form_instance_id"),
        Index("ix_review_status_reviewed_by", "reviewed_by"),
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewStatus(id={self.id}, form_instance_id={self.form_instance_id}, "
            f"is_reviewed={self.is_reviewed})>"
        )
