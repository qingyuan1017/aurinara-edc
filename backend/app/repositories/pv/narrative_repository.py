"""Persistence for PV Case_Narratives and their retained version chain.

The repository owns SQLAlchemy access for the ``pv_case_narratives`` and
``pv_narrative_versions`` tables. It only reads and stages ORM objects on the
caller-provided :class:`AsyncSession`; it never commits. The commit/rollback
boundary belongs to the request or worker unit of work so a narrative change
and its PV safety Audit_Event commit or roll back together.

The repository stores only PV-owned narrative content bound to a PV-owned
Safety_Case. It never copies an EDC clinical payload and never creates,
allocates, or mutates an EDC clinical record.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.narrative import CaseNarrative, NarrativeVersion


class NarrativeRepository:
    """Repository seam for PV case narratives and narrative versions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_narrative(
        self, narrative_id: UUID, *, include_deleted: bool = False
    ) -> CaseNarrative | None:
        """Load a Case_Narrative by id, excluding soft-deleted rows by default."""

        statement = select(CaseNarrative).where(CaseNarrative.id == narrative_id)
        if not include_deleted:
            statement = statement.where(CaseNarrative.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_narrative(
        self,
        *,
        case_id: UUID,
        text_value: str,
        authored_at: datetime,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> CaseNarrative:
        """Stage one Case_Narrative plus its authoring version (number 1) and flush.

        The authoring version carries no ``Reason_For_Change`` (Requirement 7.1).
        """

        narrative = CaseNarrative(
            case_id=case_id,
            current_text=text_value,
            current_version_number=1,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(narrative)
        await self.session.flush()

        version = NarrativeVersion(
            narrative_id=narrative.id,
            version_number=1,
            text_value=text_value,
            authored_at=authored_at,
            authored_by=actor_id,
            reason_for_change=None,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(version)
        await self.session.flush()
        return narrative

    async def max_version_number(self, narrative_id: UUID) -> int | None:
        """Return the highest live version number for a narrative.

        Prior versions are retained (never deleted or overwritten), so the next
        revision uses ``max + 1`` (Requirement 7.2).
        """

        statement = select(func.max(NarrativeVersion.version_number)).where(
            NarrativeVersion.narrative_id == narrative_id,
            NarrativeVersion.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_revision(
        self,
        *,
        narrative: CaseNarrative,
        text_value: str,
        version_number: int,
        reason_for_change: str,
        authored_at: datetime,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> NarrativeVersion:
        """Append one revision version and advance the narrative's current text.

        The prior version rows are left untouched (Requirement 7.2). The
        narrative's ``current_text``/``current_version_number`` mirror the new
        version.
        """

        version = NarrativeVersion(
            narrative_id=narrative.id,
            version_number=version_number,
            text_value=text_value,
            authored_at=authored_at,
            authored_by=actor_id,
            reason_for_change=reason_for_change,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(version)

        narrative.current_text = text_value
        narrative.current_version_number = version_number
        narrative.updated_by = actor_id
        if correlation_id is not None:
            narrative.correlation_id = correlation_id
        self.session.add(narrative)

        await self.session.flush()
        return version

    async def list_versions(
        self, narrative_id: UUID, *, include_deleted: bool = False
    ) -> list[NarrativeVersion]:
        """Return the retained versions for a narrative ordered by version number."""

        statement = (
            select(NarrativeVersion)
            .where(NarrativeVersion.narrative_id == narrative_id)
            .order_by(NarrativeVersion.version_number)
        )
        if not include_deleted:
            statement = statement.where(NarrativeVersion.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return list(result.scalars().all())


__all__ = ["NarrativeRepository"]
