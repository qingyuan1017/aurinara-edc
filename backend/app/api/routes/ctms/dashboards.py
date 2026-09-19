"""Authenticated CTMS operational dashboard routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_ctms_permission
from app.models.identity import User
from app.schemas.ctms.dashboard import CTMSDashboardResponse
from app.services.ctms_dashboard_service import ctms_dashboard_service

router = APIRouter(tags=["ctms-dashboards"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational_data_read"))]


@router.get("/studies/{study_id}/dashboard", response_model=CTMSDashboardResponse)
async def study_dashboard(study_id: UUID, session: DbSession, current_user: ReadGuard):
    """Return only scoped CTMS operational study metrics and approved signals."""
    return await ctms_dashboard_service.study_dashboard(session, study_id, current_user)


@router.get("/sites/{site_id}/dashboard", response_model=CTMSDashboardResponse)
async def site_dashboard(
    site_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    study_id: UUID | None = None,
):
    """Return only scoped CTMS operational site metrics and approved signals."""
    return await ctms_dashboard_service.site_dashboard(
        session, site_id, current_user, study_id=study_id
    )
