"""Persistence boundary for CTMS operational projections."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ctms.projection import CTMSOperationalProjection


class ProjectionRepository:
    """Read/write only the CTMS projection table, never authoritative sources."""

    async def get(
        self,
        session: AsyncSession,
        *,
        projection_type: str,
        source_module: str,
        source_record_id: UUID,
    ) -> CTMSOperationalProjection | None:
        return await session.scalar(
            select(CTMSOperationalProjection).where(
                CTMSOperationalProjection.projection_type == projection_type,
                CTMSOperationalProjection.source_module == source_module,
                CTMSOperationalProjection.source_record_id == source_record_id,
            )
        )

    async def get_by_id(
        self, session: AsyncSession, projection_id: UUID
    ) -> CTMSOperationalProjection | None:
        return await session.scalar(
            select(CTMSOperationalProjection).where(
                CTMSOperationalProjection.id == projection_id
            )
        )

    async def list(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        projection_type: str | None = None,
    ) -> Sequence[CTMSOperationalProjection]:
        statement = select(CTMSOperationalProjection).order_by(
            CTMSOperationalProjection.projected_at.desc()
        )
        if study_id is not None:
            statement = statement.where(CTMSOperationalProjection.study_id == study_id)
        if site_id is not None:
            statement = statement.where(CTMSOperationalProjection.site_id == site_id)
        if projection_type is not None:
            statement = statement.where(
                CTMSOperationalProjection.projection_type == projection_type
            )
        return (await session.scalars(statement)).all()

    async def add(self, session: AsyncSession, projection: CTMSOperationalProjection) -> CTMSOperationalProjection:
        session.add(projection)
        await session.flush()
        return projection


projection_repository = ProjectionRepository()

__all__ = ["ProjectionRepository", "projection_repository"]
