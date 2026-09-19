"""Authenticated CTMS enrollment target routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.enrollment import EnrollmentTargetStatus
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.enrollment import (
    EnrollmentTargetCreate,
    EnrollmentTargetResponse,
    EnrollmentTargetUpdate,
)
from app.services.enrollment_service import enrollment_service

router = APIRouter(tags=["ctms-enrollment"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.enrollment-management"))]


async def _list(
    study_id: UUID,
    session: AsyncSession,
    pagination: PaginationParams,
    site_id: UUID | None,
    status: EnrollmentTargetStatus | None,
):
    items = await enrollment_service.list_enrollment_targets(
        session, study_id, site_id=site_id, status=status
    )
    start = pagination.offset
    return PaginatedResponse(
        items=[
            EnrollmentTargetResponse.model_validate(x)
            for x in items[start : start + pagination.page_size]
        ],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(items),
    )


@router.post(
    "/studies/{study_id}/enrollment-targets",
    response_model=EnrollmentTargetResponse,
    status_code=201,
)
async def create_enrollment_target(
    study_id: UUID, body: EnrollmentTargetCreate, session: DbSession, current_user: WriteGuard
) -> EnrollmentTargetResponse:
    if body.study_id != study_id:
        from app.core.exceptions import ValidationError

        raise ValidationError("study_id in the path and body must match")
    return EnrollmentTargetResponse.model_validate(
        await enrollment_service.create_enrollment_target(
            session, body, current_user.id, correlation_id=get_correlation_id()
        )
    )


@router.get(
    "/studies/{study_id}/enrollment-targets",
    response_model=PaginatedResponse[EnrollmentTargetResponse],
)
async def list_study_enrollment_targets(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: EnrollmentTargetStatus | None = None,
):
    return await _list(study_id, session, pagination, site_id, status)


@router.patch("/enrollment-targets/{target_id}", response_model=EnrollmentTargetResponse)
async def update_enrollment_target(
    target_id: UUID, body: EnrollmentTargetUpdate, session: DbSession, current_user: WriteGuard
):
    target = await enrollment_service.get_enrollment_target(session, target_id)
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        target = await enrollment_service.transition_target_status(
            session,
            target,
            changes.pop("status"),
            current_user.id,
            correlation_id=get_correlation_id(),
        )
    if changes:
        for key, value in changes.items():
            setattr(target, key, value)
        target.updated_by = current_user.id
        await session.flush()
    return EnrollmentTargetResponse.model_validate(target)


@router.post("/enrollment-targets/{target_id}/transition", response_model=EnrollmentTargetResponse)
async def transition_enrollment_target(
    target_id: UUID,
    status: EnrollmentTargetStatus,
    session: DbSession,
    current_user: WriteGuard,
    reason: str | None = Query(default=None),
):
    target = await enrollment_service.get_enrollment_target(session, target_id)
    return EnrollmentTargetResponse.model_validate(
        await enrollment_service.transition_target_status(
            session,
            target,
            status,
            current_user.id,
            reason=reason,
            correlation_id=get_correlation_id(),
        )
    )


@router.get("/enrollment-targets", response_model=PaginatedResponse[EnrollmentTargetResponse])
async def list_enrollment_targets(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: EnrollmentTargetStatus | None = None,
):
    return await _list(study_id, session, pagination, site_id, status)


@router.get("/enrollment-targets/{target_id}", response_model=EnrollmentTargetResponse)
async def get_enrollment_target(target_id: UUID, session: DbSession, current_user: ReadGuard):
    return EnrollmentTargetResponse.model_validate(
        await enrollment_service.get_enrollment_target(session, target_id)
    )
