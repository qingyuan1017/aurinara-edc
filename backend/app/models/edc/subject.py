"""Subject model.

Satisfies Requirements:
  - 7.1: Subject metadata — bound to a published study version.
  - 7.2: Subject number unique within the study.
  - 22.5: Soft-delete via deleted_at column + deletion_reason + deleted_by.
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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --- Enums ---


class SubjectStatus(enum.StrEnum):
    """Subject lifecycle status (Requirement 7.3)."""

    screening = "Screening"
    screen_failed = "Screen Failed"
    enrolled = "Enrolled"
    randomized = "Randomized"
    on_treatment = "On Treatment"
    completed = "Completed"
    early_terminated = "Early Terminated"
    lost_to_follow_up = "Lost to Follow-up"
    withdrawn = "Withdrawn"


# --- Models ---


class Subject(Base):
    """Clinical trial subject — enrolled in a study at a specific site."""

    __tablename__ = "subjects"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Parent study
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )

    # Site where the subject is enrolled
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )

    # Bound study version (published version at time of enrollment)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Binds the subject to a published study version",
    )

    # Subject identifier
    subject_number: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Unique within the study"
    )

    # Lifecycle
    status: Mapped[SubjectStatus] = mapped_column(
        String(30), nullable=False, default=SubjectStatus.screening
    )

    # Ownership / audit
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft-delete (Requirement 22.5)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    study: Mapped["Study"] = relationship("Study", lazy="selectin")  # noqa: F821
    site: Mapped["Site"] = relationship("Site", lazy="selectin")  # noqa: F821
    study_version: Mapped["StudyVersion"] = relationship(  # noqa: F821
        "StudyVersion", lazy="selectin"
    )
    creator: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[created_by], lazy="selectin"
    )
    deleter: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[deleted_by], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("study_id", "subject_number", name="uq_study_subject_number"),
        Index("ix_subjects_study_id_subject_number", "study_id", "subject_number"),
        Index("ix_subjects_site_id", "site_id"),
        Index("ix_subjects_status", "status"),
        Index("ix_subjects_study_version_id", "study_version_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Subject(id={self.id}, study_id={self.study_id}, "
            f"subject_number={self.subject_number!r}, status={self.status!r})>"
        )
