"""CTMS reference-data endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.reference_data import CTMSReferenceValue, ReferenceCategory
from app.models.shared.identity import User
from app.schemas.ctms.reference_data import (
    ReferenceValueCreate,
    ReferenceValueResponse,
    ReferenceValueUpdate,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.ctms.reference_data_service import reference_data_service

router = APIRouter(prefix="/reference-values", tags=["ctms-reference-data"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]


@router.get("", response_model=PaginatedResponse[ReferenceValueResponse])
async def list_reference_values(
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    category: Annotated[ReferenceCategory | None, Query()] = None,
    active: Annotated[bool | None, Query()] = True,
):
    where = []
    if category is not None:
        where.append(CTMSReferenceValue.category == category.value)
    if active is not None:
        where.append(CTMSReferenceValue.active.is_(active))
    total = await session.scalar(select(func.count()).select_from(CTMSReferenceValue).where(*where))
    rows = await session.scalars(
        select(CTMSReferenceValue)
        .where(*where)
        .order_by(
            CTMSReferenceValue.category, CTMSReferenceValue.sort_order, CTMSReferenceValue.label
        )
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[ReferenceValueResponse.model_validate(row) for row in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(total or 0),
    )


@router.post("", response_model=ReferenceValueResponse, status_code=201)
async def create_reference_value(
    body: ReferenceValueCreate, session: DbSession, current_user: WriteGuard
):
    return ReferenceValueResponse.model_validate(
        await reference_data_service.create(
            session, body, actor=current_user, correlation_id=get_correlation_id()
        )
    )


@router.patch("/{reference_id}", response_model=ReferenceValueResponse)
async def update_reference_value(
    reference_id: UUID, body: ReferenceValueUpdate, session: DbSession, current_user: WriteGuard
):
    return ReferenceValueResponse.model_validate(
        await reference_data_service.update(
            session, reference_id, body, actor=current_user, correlation_id=get_correlation_id()
        )
    )


__all__ = ["router"]
