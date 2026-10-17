"""Export routes — export job lifecycle and file download.

Satisfies Requirements:
  - 19.1: Export job creation and status tracking (Queued → Running → Completed/Failed).
  - 19.4: Download via signed URL or authenticated streaming; download audited.
  - 21.1: All endpoints mounted under /api/v1.
  - 21.2: List endpoints return a pagination envelope.

Endpoints:
  - GET    /studies/{study_id}/exports             list exports for a study (paginated)
  - POST   /studies/{study_id}/exports             create export job
  - GET    /exports/{export_id}                    get export status/details
  - GET    /exports/{export_id}/download           download the export file
"""

import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    PaginationParams,
    get_current_user,
    get_db,
    get_permission_service,
)
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.shared.export import ExportStatus
from app.models.shared.identity import User
from app.schemas.shared.base import PaginatedResponse
from app.schemas.shared.export import (
    ExportCreate,
    ExportDatasetOption,
    ExportListResponse,
    ExportResponse,
)
from app.services.edc.operational_service import edc_operational_service
from app.services.edc.scope_service import edc_scope_service
from app.services.shared.export_service import export_service
from app.services.shared.permission_service import PermissionService

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _export_site_id(filters: dict | None) -> UUID | None:
    value = (filters or {}).get("site_id")
    return UUID(str(value)) if value else None


def _role_names(user: User, study_id: UUID) -> set[str]:
    return {
        assignment.role.name
        for assignment in user.user_roles
        if assignment.study_id is None or assignment.study_id == study_id
    }


# ---------------------------------------------------------------------------
# Study-scoped export collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_exports_router = APIRouter(prefix="/studies", tags=["exports"])


@study_exports_router.get(
    "/{study_id}/exports/datasets",
    response_model=list[ExportDatasetOption],
)
async def list_export_datasets(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> list[ExportDatasetOption]:
    """List authorized raw datasets available to the export request."""
    edc_scope_service.authorized_site_ids(current_user, permission_service, "data.export", study_id)
    return await edc_operational_service.export_dataset_catalog(
        session,
        study_id,
        role_names=_role_names(current_user, study_id),
    )


@study_exports_router.get(
    "/{study_id}/exports",
    response_model=PaginatedResponse[ExportListResponse],
)
async def list_exports(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[ExportListResponse]:
    """List export jobs for a study (paginated).

    Permission: data.export
    Requirement 21.2: Paginated response envelope.
    """
    authorized_site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, "data.export", study_id
    )
    result = await export_service.list_exports(
        session,
        study_id,
        pagination=pagination,
        authorized_site_ids=authorized_site_ids,
    )
    return PaginatedResponse[ExportListResponse](
        items=[ExportListResponse.model_validate(e) for e in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_exports_router.post(
    "/{study_id}/exports",
    response_model=ExportResponse,
    status_code=201,
)
async def create_export(
    study_id: UUID,
    body: ExportCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> ExportResponse:
    """Create an export job for a study.

    Permission: data.export
    Requirement 19.1: Export job creation with status Queued.
    """
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "data.export",
        study_id=study_id,
        site_id=body.filters.site_id if body.filters else None,
    )
    export = await export_service.create_export(
        session,
        study_id=study_id,
        export_type=body.export_type,
        filters=body.filters.model_dump(exclude_none=True) if body.filters else None,
        actor_id=current_user.id,
    )
    return ExportResponse.model_validate(export)


# ---------------------------------------------------------------------------
# Single-export operations (mounted at /exports)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/{export_id}", response_model=ExportResponse)
async def get_export(
    export_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> ExportResponse:
    """Get export job status and details.

    Permission: data.export
    """
    export = await export_service.get_export(session, export_id)
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "data.export",
        study_id=export.study_id,
        site_id=_export_site_id(export.filters),
    )
    return ExportResponse.model_validate(export)


@router.post("/{export_id}/retry", response_model=ExportResponse, status_code=201)
async def retry_export(
    export_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> ExportResponse:
    """Create a new queued attempt from a failed export's immutable inputs."""
    failed = await export_service.get_export(session, export_id)
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "data.export",
        study_id=failed.study_id,
        site_id=_export_site_id(failed.filters),
    )
    if failed.status != ExportStatus.failed:
        raise BusinessRuleError(
            message="Only failed exports can be retried",
            details={"export_id": str(export_id), "current_status": failed.status},
        )
    retried = await export_service.create_export(
        session,
        study_id=failed.study_id,
        export_type=failed.export_type,
        filters=failed.filters,
        actor_id=current_user.id,
    )
    return ExportResponse.model_validate(retried)


@router.get("/{export_id}/download", response_class=FileResponse)
async def download_export(
    export_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FileResponse:
    """Download an export file through an authenticated response.

    Permission: data.export
    Requirement 19.4: Provide the file and record an Audit_Event for the download.
    """
    export = await export_service.get_export(session, export_id)
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "data.export",
        study_id=export.study_id,
        site_id=_export_site_id(export.filters),
    )

    if export.status != ExportStatus.completed:
        raise BusinessRuleError(
            message="Export is not ready for download",
            details={
                "export_id": str(export_id),
                "current_status": export.status,
                "required_status": ExportStatus.completed,
            },
        )

    if not export.file_path:
        raise BusinessRuleError(
            message="Export file path is not available",
            details={"export_id": str(export_id)},
        )

    file_path = Path(export.file_path)
    if not file_path.is_file():
        raise NotFoundError(
            message="Export file content was not found",
            details={"export_id": str(export_id)},
        )

    await export_service.record_download(
        session,
        export,
        actor_id=current_user.id,
    )

    media_type = {
        ".csv": "text/csv",
        ".zip": "application/zip",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".json": "application/json",
        ".xpt": "application/x-sas-xport",
        ".xml": "application/xml",
    }.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file_path.name,
    )
