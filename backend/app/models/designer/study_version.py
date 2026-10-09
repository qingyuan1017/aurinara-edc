"""Design_Version model — design-time version metadata owned by the Designer module.

This module owns the **design-time version metadata** aspect of a study. The
`Study` *identity* remains canonical and shared in ``app.models.edc.study``
(no competing identity is minted here); only the versioned, design-time
lifecycle metadata (``Design_Version``) lives in the Designer package.

The ``StudyVersion`` ORM class is reused directly as ``Design_Version``: its
existing ``status`` of ``draft``/``published`` maps to ``Draft_Design`` /
``Published_Design``, ``amended_from_version_id`` models amendment lineage, and
``published_at`` / ``published_by`` capture the publication actor and timestamp.

The move is a code-layer ownership change only — the backing table
(``study_versions``) and all columns are unchanged, so stored values are
preserved and the migration is purely additive.

Satisfies Requirements:
  - 1.1: Design-time version metadata owned by the Designer module.
  - 1.5: `Study` identity remains canonical/shared (no competing identity).
  - 2.1: Draft Design_Version lifecycle (draft → published).
  - 2.2: Publication records actor and timestamp.
  - 11.1: Ownership reassignment with no table/column renames.
  - 5.5: Each design-time child references exactly one Design_Version (via FK).
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:  # avoid a runtime import cycle; Study identity stays in edc
    from app.models.edc.study import Study


class StudyVersionStatus(enum.StrEnum):
    """Design_Version status (Requirement 2.1).

    ``draft`` maps to ``Draft_Design`` and ``published`` maps to
    ``Published_Design`` in the refactored domain language.
    """

    draft = "draft"
    published = "published"


class StudyVersion(Base):
    """Versioned snapshot of a study's design — the ``Design_Version`` entity.

    Each published version is immutable; design-time definitions (forms,
    sections, fields, visits, codelists, edit checks, …) reference a specific
    version. New drafts are created for amendments (Requirement 2.9).

    The ``study`` relationship binds to the canonical shared ``Study`` identity
    which continues to live in ``app.models.edc.study``; this class does not
    redefine or compete with that identity.
    """

    __tablename__ = "study_versions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Parent study (canonical shared identity; FK by table name)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )

    # Version identifier
    version_number: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="e.g. 1.0, 2.0"
    )

    # Lifecycle
    status: Mapped[StudyVersionStatus] = mapped_column(
        String(20), nullable=False, default=StudyVersionStatus.draft
    )

    # Amendment info (Requirements 2.9-2.11)
    amendment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    amended_from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="RESTRICT"),
        nullable=True,
        comment="Published source version for an amendment",
    )

    # Publication (Requirement 2.2)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships (resolved by string against the shared ORM registry)
    study: Mapped[Study] = relationship("Study", back_populates="versions")
    amended_from: Mapped[StudyVersion | None] = relationship(
        "StudyVersion",
        remote_side="StudyVersion.id",
        foreign_keys=[amended_from_version_id],
        back_populates="amendments",
    )
    amendments: Mapped[list[StudyVersion]] = relationship(
        "StudyVersion",
        foreign_keys=[amended_from_version_id],
        back_populates="amended_from",
    )

    __table_args__ = (
        UniqueConstraint("study_id", "version_number", name="uq_study_version_number"),
        Index("ix_study_versions_study_id", "study_id"),
        Index("ix_study_versions_status", "status"),
        Index("ix_study_versions_amended_from_version_id", "amended_from_version_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudyVersion(id={self.id}, study_id={self.study_id}, "
            f"version={self.version_number!r}, status={self.status!r})>"
        )
