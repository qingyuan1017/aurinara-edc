"""Repository operations for edit-check definitions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.edit_check import EditCheck


class EditCheckRepository:
    """Encapsulates edit-check definition persistence and retrieval."""

    async def get(self, session: AsyncSession, edit_check_id: UUID) -> EditCheck | None:
        return await session.get(EditCheck, edit_check_id)

    async def list_for_version(
        self, session: AsyncSession, study_version_id: UUID
    ) -> list[EditCheck]:
        result = await session.execute(
            select(EditCheck)
            .where(EditCheck.study_version_id == study_version_id)
            .order_by(EditCheck.created_at, EditCheck.name)
        )
        return list(result.scalars().all())

    async def add(self, session: AsyncSession, edit_check: EditCheck) -> EditCheck:
        session.add(edit_check)
        await session.flush()
        return edit_check

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()
