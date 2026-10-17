"""Authenticated routes for expanded CTMS Study Operations resources."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.exceptions import BusinessRuleError
from app.core.request_context import get_correlation_id
from app.models.ctms.study_operation import StudyOperationRecord, StudyOperationResource
from app.models.shared.identity import User
from app.schemas.ctms.study_operation import (
    StudyOperationCreate,
    StudyOperationResponse,
    StudyOperationUpdate,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.ctms.study_operation_service import study_operation_service

router = APIRouter(tags=["ctms-study-operations"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]
DEDICATED_RESOURCES = {
    StudyOperationResource.RACT,
    StudyOperationResource.KRI,
    StudyOperationResource.PROTOCOL_DEVIATION,
    StudyOperationResource.ICF,
    StudyOperationResource.TRACKING_LOG,
}


def _require_legacy_write_compatibility(resource: StudyOperationResource) -> None:
    if resource in DEDICATED_RESOURCES:
        raise BusinessRuleError(
            "This resource now uses its dedicated versioned study workspace service",
            {"reason": "DEDICATED_WORKFLOW_REQUIRED", "resource": resource.value},
        )


@router.get(
    "/studies/{study_id}/study-operations/{resource}",
    response_model=PaginatedResponse[StudyOperationResponse],
)
async def list_study_operation_records(
    study_id: UUID,
    resource: StudyOperationResource,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: str | None = None,
    owner_id: UUID | None = None,
    record_subtype: str | None = None,
):
    conditions = [
        StudyOperationRecord.study_id == study_id,
        StudyOperationRecord.resource_type == resource.value,
        StudyOperationRecord.deleted_at.is_(None),
    ]
    if site_id is not None:
        conditions.append(StudyOperationRecord.site_id == site_id)
    if status:
        conditions.append(StudyOperationRecord.status == status)
    if owner_id is not None:
        conditions.append(StudyOperationRecord.owner_id == owner_id)
    if record_subtype:
        conditions.append(StudyOperationRecord.record_subtype == record_subtype)
    total = int(
        await session.scalar(
            select(func.count()).select_from(StudyOperationRecord).where(*conditions)
        )
        or 0
    )
    rows = await session.scalars(
        select(StudyOperationRecord)
        .where(*conditions)
        .order_by(StudyOperationRecord.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[StudyOperationResponse.model_validate(row) for row in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.post(
    "/studies/{study_id}/study-operations/{resource}",
    response_model=StudyOperationResponse,
    status_code=201,
)
async def create_study_operation_record(
    study_id: UUID,
    resource: StudyOperationResource,
    body: StudyOperationCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    _require_legacy_write_compatibility(resource)
    record = await study_operation_service.create(
        session,
        study_id,
        resource,
        body,
        actor_id=current_user.id,
        correlation_id=get_correlation_id(),
    )
    return StudyOperationResponse.model_validate(record)


@router.get(
    "/studies/{study_id}/study-operations/{resource}/{record_id}",
    response_model=StudyOperationResponse,
)
async def get_study_operation_record(
    study_id: UUID,
    resource: StudyOperationResource,
    record_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
):
    return StudyOperationResponse.model_validate(
        await study_operation_service.resolve(session, study_id, resource, record_id)
    )


@router.patch(
    "/studies/{study_id}/study-operations/{resource}/{record_id}",
    response_model=StudyOperationResponse,
)
async def update_study_operation_record(
    study_id: UUID,
    resource: StudyOperationResource,
    record_id: UUID,
    body: StudyOperationUpdate,
    session: DbSession,
    current_user: WriteGuard,
):
    _require_legacy_write_compatibility(resource)
    return StudyOperationResponse.model_validate(
        await study_operation_service.update(
            session,
            study_id,
            resource,
            record_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


__all__ = ["router"]
