"""Persistence boundary for projection rebuild generations and watermarks."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ctms.projection_rebuild import CTMSProjectionRebuildState


class ProjectionRebuildRepository:
    """Persist rebuild metadata only; never read or write authoritative data."""

    async def add(
        self, session: AsyncSession, state: CTMSProjectionRebuildState
    ) -> CTMSProjectionRebuildState:
        session.add(state)
        await session.flush()
        return state

    async def get_by_generation(
        self, session: AsyncSession, generation: UUID
    ) -> CTMSProjectionRebuildState | None:
        return await session.scalar(
            select(CTMSProjectionRebuildState).where(
                CTMSProjectionRebuildState.generation == generation
            )
        )

    async def latest(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID | None,
        projection_type: str,
        source_module: str,
    ) -> CTMSProjectionRebuildState | None:
        statement = (
            select(CTMSProjectionRebuildState)
            .where(
                CTMSProjectionRebuildState.scope_study_id == study_id,
                CTMSProjectionRebuildState.scope_site_id == site_id,
                CTMSProjectionRebuildState.projection_type == projection_type,
                CTMSProjectionRebuildState.source_module == source_module,
            )
            .order_by(CTMSProjectionRebuildState.started_at.desc())
            .limit(1)
        )
        return await session.scalar(statement)


projection_rebuild_repository = ProjectionRebuildRepository()

__all__ = ["ProjectionRebuildRepository", "projection_rebuild_repository"]
