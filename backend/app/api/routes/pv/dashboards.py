"""PV safety dashboard and report routes.

Thin, authenticated read handlers under ``/api/v1/pv`` that delegate to the
``PV_Dashboard_Service``. The service computes every metric from in-scope PV
safety records as of the request timestamp, restricts results to the requesting
user's Authorization_Scope, and surfaces any approved EDC/CTMS projection only
as read-only, source-labeled fields. No route mutates any record.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.models.identity import User
from app.schemas.pv.dashboard import SafetySiteDashboard, SafetyStudyDashboard
from app.services.pv_dashboard_service import PVDashboardService

router = APIRouter(tags=["pv-dashboards"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]

_dashboard_service = PVDashboardService()


@router.get("/studies/{study_id}/dashboard", response_model=SafetyStudyDashboard)
async def study_dashboard(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> SafetyStudyDashboard:
    """Return the scoped PV safety study dashboard as of the request timestamp."""

    return await _dashboard_service.study_dashboard(session, study_id, current_user)


@router.get("/sites/{site_id}/dashboard", response_model=SafetySiteDashboard)
async def site_dashboard(
    site_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    study_id: UUID | None = None,
) -> SafetySiteDashboard:
    """Return the scoped PV safety site dashboard with only in-scope metrics."""

    return await _dashboard_service.site_dashboard(
        session, site_id, current_user, study_id=study_id
    )
