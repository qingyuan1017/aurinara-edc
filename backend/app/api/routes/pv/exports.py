"""PV safety export routes on shared export-job infrastructure.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``PV_Export_Service``. The service validates the requested format and filters
(including the 1,830-day span limit), records the PV export job with
``module="PV"`` so PV export content stays separate from EDC/CTMS content, and
enforces the 900-second owner-only download window with a download Audit_Event.
No route mutates an EDC clinical or CTMS operational record.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.core.pv import Module
from app.models.export import Export
from app.models.identity import User
from app.schemas.pv.contracts import PVPaginatedResponse, PVPaginationParams
from app.schemas.pv.export import PVExportCreate, PVExportResponse
from app.services.pv_export_service import pv_export_service

router = APIRouter(tags=["pv-exports"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
CreateGuard = Annotated[User, Depends(require_pv_permission("safety_export.create"))]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]


@router.post(
    "/studies/{study_id}/exports",
    response_model=PVExportResponse,
    status_code=201,
)
async def create_export(
    study_id: UUID,
    body: PVExportCreate,
    session: DbSession,
    current_user: CreateGuard,
) -> PVExportResponse:
    """Create a Queued PV safety export job scoped to the study."""

    export = await pv_export_service.create_export(
        session,
        study_id=study_id,
        export_type=body.export_type,
        filters=body.filters,
        actor=build_actor(current_user),
    )
    return PVExportResponse.model_validate(export)


@router.get(
    "/studies/{study_id}/exports",
    response_model=PVPaginatedResponse[PVExportResponse],
)
async def list_exports(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PVPaginationParams, Depends()],
) -> PVPaginatedResponse[PVExportResponse]:
    """List PV-owned safety export jobs for a study."""

    stmt = (
        select(Export)
        .where(Export.study_id == study_id, Export.module == Module.PV.value)
        .order_by(Export.created_at.desc())
    )
    result = await session.execute(stmt)
    exports = list(result.scalars().all())
    start = pagination.offset
    window = exports[start : start + pagination.page_size]
    return PVPaginatedResponse[PVExportResponse](
        items=[PVExportResponse.model_validate(export) for export in window],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(exports),
    )


@router.get("/exports/{export_id}", response_model=PVExportResponse)
async def get_export(
    export_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> PVExportResponse:
    """Return one PV-owned export job by identifier."""

    from app.core.exceptions import NotFoundError

    stmt = select(Export).where(
        Export.id == export_id, Export.module == Module.PV.value
    )
    result = await session.execute(stmt)
    export = result.scalar_one_or_none()
    if export is None:
        raise NotFoundError(
            message="PV safety export was not found",
            details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_export"},
        )
    return PVExportResponse.model_validate(export)


@router.get("/exports/{export_id}/download", response_model=dict)
async def download_export(
    export_id: UUID,
    session: DbSession,
    current_user: CreateGuard,
) -> dict:
    """Authorize and audit a download of a completed PV safety export.

    The service verifies ownership and the 900-second window and records the
    download Audit_Event; the resolved file reference is returned for the caller
    to fetch.
    """

    export = await pv_export_service.authorize_download(
        session,
        export_id=export_id,
        actor=build_actor(current_user),
    )
    return {
        "export_id": str(export.id),
        "file_path": export.file_path,
        "file_size": export.file_size,
    }
