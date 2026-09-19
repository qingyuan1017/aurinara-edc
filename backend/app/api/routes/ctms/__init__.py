"""Versioned CTMS API route package.

All CTMS endpoints are mounted below ``/api/v1/ctms``. The resource routers
are intentionally separate from EDC routes so disabling CTMS never changes
EDC route ownership or behavior.
"""

from fastapi import APIRouter

from app.api.routes.ctms.capabilities import router as capabilities_router
from app.api.routes.ctms.contacts import router as contacts_router
from app.api.routes.ctms.coordination import router as coordination_router
from app.api.routes.ctms.dashboards import router as dashboards_router
from app.api.routes.ctms.enrollment import router as enrollment_router
from app.api.routes.ctms.exports import router as exports_router
from app.api.routes.ctms.health import router as health_router
from app.api.routes.ctms.milestones import router as milestones_router
from app.api.routes.ctms.monitoring import router as monitoring_router
from app.api.routes.ctms.projections import router as projections_router
from app.api.routes.ctms.reports import router as reports_router
from app.api.routes.ctms.sites import (
    activation_actions_router,
    operational_sites_router,
)
from app.api.routes.ctms.sites import (
    router as sites_router,
)
from app.api.routes.ctms.studies import operational_studies_router
from app.api.routes.ctms.studies import router as studies_router
from app.api.routes.ctms.tasks import router as tasks_router
from app.core.openapi import CTMS_ERROR_RESPONSES

# Resource route modules are present as additive boundaries and will register
# concrete endpoints as their corresponding implementation tasks land.
router = APIRouter(prefix="/ctms", responses=CTMS_ERROR_RESPONSES)
for resource_router in (
    capabilities_router,
    health_router,
    studies_router,
    operational_studies_router,
    sites_router,
    operational_sites_router,
    activation_actions_router,
    enrollment_router,
    milestones_router,
    monitoring_router,
    tasks_router,
    contacts_router,
    projections_router,
    coordination_router,
    dashboards_router,
    reports_router,
    exports_router,
):
    router.include_router(resource_router)

__all__ = ["router"]
