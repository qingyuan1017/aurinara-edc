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
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError
from app.models.export import ExportStatus
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.export import (
    ExportCreate,
    ExportListResponse,
    ExportResponse,
)
from app.services.export_service import export_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study-scoped export collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_exports_router = APIRouter(prefix="/studies", tags=["exports"])


@study_exports_router.get(
    "/{study_id}/exports",
    response_model=PaginatedResponse[ExportListResponse],
)
async def list_exports(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("data.export"))],
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[ExportListResponse]:
    """List export jobs for a study (paginated).

    Permission: data.export
    Requirement 21.2: Paginated response envelope.
    """
    result = await export_service.list_exports(session, study_id, pagination=pagination)
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
    current_user: Annotated[User, Depends(require_permission("data.export"))],
) -> ExportResponse:
    """Create an export job for a study.

    Permission: data.export
    Requirement 19.1: Export job creation with status Queued.
    """
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
    current_user: Annotated[User, Depends(require_permission("data.export"))],
) -> ExportResponse:
    """Get export job status and details.

    Permission: data.export
    """
    export = await export_service.get_export(session, export_id)
    return ExportResponse.model_validate(export)


@router.get("/{export_id}/download", response_model=dict)
async def download_export(
    export_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("data.export"))],
) -> dict:
    """Download an export file (returns file_path or download URL).

    Permission: data.export
    Requirement 19.4: Provide the file and record an Audit_Event for the download.

    Returns a JSON object with the download URL or file path. In production
    this would return a signed S3 URL or stream the file; here we return the
    stored file_path for the caller to resolve.
    """
    export = await export_service.get_export(session, export_id)

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

    # Record audit event for the download (Requirement 19.4)
    await audit_service.record(
        session,
        entity_type="export",
        entity_id=export.id,
        action="download",
        study_id=export.study_id,
        actor_id=current_user.id,
        new_value=f"file_path={export.file_path}",
    )

    return {
        "export_id": str(export.id),
        "file_path": export.file_path,
        "file_size": export.file_size,
    }
