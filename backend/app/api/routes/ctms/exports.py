"""Authenticated CTMS operational export routes using shared job infrastructure."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, get_permission_service, require_ctms_permission
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.request_context import get_correlation_id
from app.core.storage import get_object_storage
from app.models.export import Export, ExportStatus
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.export import OperationalExportCreate, OperationalExportResponse
from app.services.export_service import export_service
from app.services.permission_service import PermissionService

router = APIRouter(tags=["ctms-exports"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]


def _check_ctms(job: Export) -> None:
    if job.module != "CTMS" or job.content_owner != "CTMS":
        raise NotFoundError("CTMS operational export was not found")


async def _load_scoped_job(
    export_id: UUID,
    session: AsyncSession,
    current_user: User,
    permission_service: PermissionService,
) -> Export:
    job = await export_service.get_export(session, export_id)
    _check_ctms(job)
    permission_service.require(
        current_user,
        "ctms.operational-data-read",
        study_id=job.study_id,
    )
    return job


@router.post(
    "/studies/{study_id}/exports", response_model=OperationalExportResponse, status_code=201
)
async def create_operational_export(
    study_id: UUID, body: OperationalExportCreate, session: DbSession, current_user: WriteGuard
):
    export = await export_service.create_ctms_export(
        session,
        study_id=study_id,
        export_type=body.export_type.value,
        filters=body.filters,
        actor_id=current_user.id,
        correlation_id=get_correlation_id(),
    )
    return OperationalExportResponse.model_validate(export)


@router.get(
    "/studies/{study_id}/exports", response_model=PaginatedResponse[OperationalExportResponse]
)
async def list_operational_exports(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    conditions = [
        Export.study_id == study_id,
        Export.module == "CTMS",
        Export.content_owner == "CTMS",
    ]
    total = int(
        await session.scalar(select(func.count()).select_from(Export).where(*conditions)) or 0
    )
    jobs = await session.scalars(
        select(Export)
        .where(*conditions)
        .order_by(Export.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[OperationalExportResponse.model_validate(x) for x in jobs],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/exports/{export_id}", response_model=OperationalExportResponse)
async def get_operational_export(
    export_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
):
    job = await _load_scoped_job(export_id, session, current_user, permission_service)
    return OperationalExportResponse.model_validate(job)


@router.get("/exports/{export_id}/download")
async def download_operational_export(
    export_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
):
    job = await _load_scoped_job(export_id, session, current_user, permission_service)
    if job.status != ExportStatus.completed or not job.file_path:
        raise BusinessRuleError(
            "Operational export is not ready for download",
            {"export_id": str(export_id), "status": str(job.status)},
        )
    try:
        content = await get_object_storage().get(job.file_path)
    except FileNotFoundError as exc:
        raise NotFoundError(
            "Operational export content was not found",
            {"export_id": str(export_id)},
        ) from exc
    await export_service.record_download(
        session, job, actor_id=current_user.id, correlation_id=get_correlation_id()
    )
    media_type = {
        "csv": "text/csv",
        "json": "application/json",
        "excel": "application/vnd.ms-excel",
    }.get(job.export_type, "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="ctms_export_{job.id}.{job.export_type}"'},
    )
