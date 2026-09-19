"""Authenticated read-only CTMS operational projection routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.exceptions import NotFoundError
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.projection import ProjectionResponse

router = APIRouter(tags=["ctms-projections"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]


@router.get("/studies/{study_id}/projections", response_model=PaginatedResponse[ProjectionResponse])
async def list_projections(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    statement = select(CTMSOperationalProjection).where(
        CTMSOperationalProjection.study_id == study_id
    ).order_by(CTMSOperationalProjection.projected_at.desc())
    projections = list((await session.scalars(statement)).all())
    page = projections[pagination.offset : pagination.offset + pagination.page_size]
    return PaginatedResponse(
        items=[ProjectionResponse.model_validate(item) for item in page],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(projections),
    )


@router.get("/projections/{projection_id}", response_model=ProjectionResponse)
async def get_projection(projection_id: UUID, session: DbSession, current_user: ReadGuard):
    projection = await session.scalar(
        select(CTMSOperationalProjection).where(
            CTMSOperationalProjection.id == projection_id
        )
    )
    if projection is None:
        raise NotFoundError(
            "CTMS projection was not found", {"projection_id": str(projection_id)}
        )
    return ProjectionResponse.model_validate(projection)
