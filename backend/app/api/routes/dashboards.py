"""Dashboard routes — study-level and site-level aggregation metrics.

Thin route handlers that delegate to DashboardService for read-only
aggregation queries.

Satisfies Requirements:
  - 20.1: Study dashboard: subject counts by status, form completion, open queries.
  - 20.2: Site dashboard: site-level progress.
  - 20.3: Query metrics: open/answered/overdue counts and aging.
  - 21.1: All endpoints mounted under /api/v1.

Endpoints:
  - GET /studies/{study_id}/dashboard     study dashboard (study.read)
  - GET /sites/{site_id}/dashboard        site dashboard (site.read)
  - GET /studies/{study_id}/query-metrics  query metrics (study.read)
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.identity import User
from app.schemas.dashboard import QueryMetrics, SiteDashboard, StudyDashboard
from app.services.dashboard_service import dashboard_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study dashboard routes
# ---------------------------------------------------------------------------

study_dashboard_router = APIRouter(prefix="/studies", tags=["dashboards"])


@study_dashboard_router.get(
    "/{study_id}/dashboard",
    response_model=StudyDashboard,
)
async def get_study_dashboard(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> StudyDashboard:
    """Get study-level dashboard metrics.

    Permission: study.read
    Requirement 20.1: Subject counts by status, form completion, open queries.
    """
    return await dashboard_service.study_dashboard(session, study_id)


@study_dashboard_router.get(
    "/{study_id}/query-metrics",
    response_model=QueryMetrics,
)
async def get_query_metrics(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> QueryMetrics:
    """Get query metrics for a study.

    Permission: study.read
    Requirement 20.3: Open/answered/overdue counts and aging.
    """
    return await dashboard_service.query_metrics(session, study_id)


# ---------------------------------------------------------------------------
# Site dashboard routes
# ---------------------------------------------------------------------------

site_dashboard_router = APIRouter(prefix="/sites", tags=["dashboards"])


@site_dashboard_router.get(
    "/{site_id}/dashboard",
    response_model=SiteDashboard,
)
async def get_site_dashboard(
    site_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.read"))],
) -> SiteDashboard:
    """Get site-level dashboard metrics.

    Permission: site.read
    Requirement 20.2: Site-level progress metrics.
    """
    return await dashboard_service.site_dashboard(session, site_id)
