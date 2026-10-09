"""Repository operations for Design_Version persistence and retrieval.

Owned by the Designer module (the Design_Version lifecycle). The backing table
(``study_versions``) and its stored values are unchanged — this is a code-layer
ownership move (R2, R11.1).

Satisfies Requirements:
  - 2.1: Draft/published Design_Version persistence and history queries.
  - 11.1: Ownership reassignment without data changes.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.designer.study_version import StudyVersion, StudyVersionStatus


class StudyVersionRepository:
    """Encapsulates StudyVersion persistence and version-history queries."""

    async def get(self, session: AsyncSession, version_id: UUID) -> StudyVersion | None:
        return await session.get(StudyVersion, version_id)

    async def list_for_study(
        self, session: AsyncSession, study_id: UUID
    ) -> list[StudyVersion]:
        result = await session.execute(
            select(StudyVersion)
            .where(StudyVersion.study_id == study_id)
            .order_by(StudyVersion.created_at, StudyVersion.version_number)
        )
        return list(result.scalars().all())

    async def latest_published(
        self, session: AsyncSession, study_id: UUID
    ) -> StudyVersion | None:
        result = await session.execute(
            select(StudyVersion)
            .where(
                StudyVersion.study_id == study_id,
                StudyVersion.status == StudyVersionStatus.published,
            )
            .order_by(StudyVersion.published_at.desc(), StudyVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def draft_for_study(
        self, session: AsyncSession, study_id: UUID
    ) -> StudyVersion | None:
        result = await session.execute(
            select(StudyVersion)
            .where(
                StudyVersion.study_id == study_id,
                StudyVersion.status == StudyVersionStatus.draft,
            )
            .order_by(StudyVersion.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def add(
        self, session: AsyncSession, version: StudyVersion
    ) -> StudyVersion:
        session.add(version)
        await session.flush()
        return version
