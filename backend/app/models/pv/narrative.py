"""PV Case_Narrative persistence (versioned narratives).

A ``Case_Narrative`` belongs to exactly one ``Safety_Case`` and keeps a linear
history of ``Narrative_Version`` rows. Version 1 is the authoring version;
every revision appends a new version with the revising actor, timestamp, and a
``Reason_For_Change`` while retaining all prior versions immutably. The
narrative's current text mirrors the latest version's text.

Narrative text is non-empty after trimming and at most 20,000 characters; a
revision ``Reason_For_Change`` is non-empty after trimming and at most 4,000
characters. Those rules are enforced by the ``Narrative_Service`` and,
defensively, by database check constraints. No PV table copies an EDC clinical
payload, and no PV table creates, allocates, or mutates an EDC clinical record.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pv.common import PVBase

# Narrative-text and Reason_For_Change bounds (Requirements 7.1, 7.2, 7.3).
NARRATIVE_TEXT_MAX_LENGTH = 20_000
NARRATIVE_REASON_MAX_LENGTH = 4_000

# Partial-index predicate that excludes soft-deleted rows (Requirement 17.5).
_NOT_DELETED = text("deleted_at IS NULL")


class CaseNarrative(PVBase):
    """The current narrative for one Safety_Case with a retained version chain.

    ``current_text`` mirrors the most recently authored/revised version's text.
    ``current_version_number`` is the sequence number of that version. The
    versions themselves live in :class:`NarrativeVersion` and are never deleted
    or overwritten.
    """

    __tablename__ = "pv_case_narratives"

    case_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False
    )
    current_text: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    versions: Mapped[list[NarrativeVersion]] = relationship(
        "NarrativeVersion", back_populates="narrative", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            f"length(current_text) BETWEEN 1 AND {NARRATIVE_TEXT_MAX_LENGTH}",
            name="ck_pv_case_narratives_text_length",
        ),
        CheckConstraint(
            "current_version_number >= 1",
            name="ck_pv_case_narratives_version_number",
        ),
        Index(
            "ix_pv_case_narratives_case",
            "case_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


class NarrativeVersion(PVBase):
    """One immutable version of a Case_Narrative.

    ``version_number`` is 1 for the authoring version and ``max + 1`` for each
    revision. ``reason_for_change`` is ``NULL`` for the authoring version and a
    non-empty (after trim), <= 4,000-character value for a revision. Prior
    versions are retained; a submitted version's captured text is never
    modified.
    """

    __tablename__ = "pv_narrative_versions"

    narrative_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pv_case_narratives.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text_value: Mapped[str] = mapped_column(Text, nullable=False)
    authored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    authored_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason_for_change: Mapped[str | None] = mapped_column(Text, nullable=True)

    narrative: Mapped[CaseNarrative] = relationship(
        "CaseNarrative", back_populates="versions", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            f"length(text_value) BETWEEN 1 AND {NARRATIVE_TEXT_MAX_LENGTH}",
            name="ck_pv_narrative_versions_text_length",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_pv_narrative_versions_version_number",
        ),
        CheckConstraint(
            "reason_for_change IS NULL "
            f"OR length(reason_for_change) BETWEEN 1 AND {NARRATIVE_REASON_MAX_LENGTH}",
            name="ck_pv_narrative_versions_reason_length",
        ),
        # The authoring version (1) carries no Reason_For_Change; every later
        # version must record one (Requirements 7.1, 7.2).
        CheckConstraint(
            "(version_number = 1 AND reason_for_change IS NULL) "
            "OR (version_number > 1 AND reason_for_change IS NOT NULL)",
            name="ck_pv_narrative_versions_reason_presence",
        ),
        # One sequence number per narrative among live versions.
        Index(
            "uq_pv_narrative_versions_narrative_sequence",
            "narrative_id",
            "version_number",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_narrative_versions_narrative",
            "narrative_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


__all__ = [
    "NARRATIVE_REASON_MAX_LENGTH",
    "NARRATIVE_TEXT_MAX_LENGTH",
    "CaseNarrative",
    "NarrativeVersion",
]
