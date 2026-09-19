"""Authenticated CTMS operational subject milestone routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.enrollment import OperationalSubjectStatus
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.enrollment import OperationalMilestoneCreate, OperationalMilestoneResponse
from app.services.enrollment_service import enrollment_service

router = APIRouter(tags=["ctms-milestones"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.enrollment-management"))]


async def _items(
    study_id: UUID,
    session: AsyncSession,
    pagination: PaginationParams,
    site_id: UUID | None,
    subject_id: UUID | None,
    status: OperationalSubjectStatus | None,
):
    items = await enrollment_service.list_operational_milestones(
        session, study_id, site_id=site_id, subject_id=subject_id, status=status
    )
    start = pagination.offset
    return PaginatedResponse(
        items=[
            OperationalMilestoneResponse.model_validate(x)
            for x in items[start : start + pagination.page_size]
        ],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(items),
    )


@router.post(
    "/subjects/{subject_id}/operational-milestones",
    response_model=OperationalMilestoneResponse,
    status_code=201,
)
async def record_subject_milestone(
    subject_id: UUID, body: OperationalMilestoneCreate, session: DbSession, current_user: WriteGuard
):
    if body.subject_id != subject_id:
        from app.core.exceptions import ValidationError

        raise ValidationError("subject_id in the path and body must match")
    return OperationalMilestoneResponse.model_validate(
        await enrollment_service.record_operational_milestone(
            session, body, current_user.id, correlation_id=get_correlation_id()
        )
    )


@router.get(
    "/studies/{study_id}/operational-milestones",
    response_model=PaginatedResponse[OperationalMilestoneResponse],
)
async def list_study_milestones(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
    status: OperationalSubjectStatus | None = None,
):
    return await _items(study_id, session, pagination, site_id, subject_id, status)


@router.post(
    "/operational-milestones", response_model=OperationalMilestoneResponse, status_code=201
)
async def record_operational_milestone(
    body: OperationalMilestoneCreate, session: DbSession, current_user: WriteGuard
):
    return OperationalMilestoneResponse.model_validate(
        await enrollment_service.record_operational_milestone(
            session, body, current_user.id, correlation_id=get_correlation_id()
        )
    )


@router.get(
    "/operational-milestones", response_model=PaginatedResponse[OperationalMilestoneResponse]
)
async def list_operational_milestones(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
    status: OperationalSubjectStatus | None = None,
):
    return await _items(study_id, session, pagination, site_id, subject_id, status)
