"""Versioned PV/Safety API route package.

All PV endpoints are mounted below ``/api/v1/pv``. The resource routers are
intentionally separate from EDC and CTMS routes so disabling PV never changes
EDC clinical or CTMS operational route ownership or behavior.
"""

from fastapi import APIRouter

from app.api.routes.pv.assessments import router as assessments_router
from app.api.routes.pv.attachments import router as attachments_router
from app.api.routes.pv.audit import router as audit_router
from app.api.routes.pv.capabilities import router as capabilities_router
from app.api.routes.pv.cases import router as cases_router
from app.api.routes.pv.coding import router as coding_router
from app.api.routes.pv.dashboards import router as dashboards_router
from app.api.routes.pv.exports import router as exports_router
from app.api.routes.pv.health import router as health_router
from app.api.routes.pv.narratives import router as narratives_router
from app.api.routes.pv.reconciliation import router as reconciliation_router
from app.api.routes.pv.reports import router as reports_router
from app.core.openapi import PV_ERROR_RESPONSES

# Resource route modules are present as additive boundaries and register
# concrete endpoints as their corresponding implementation tasks land.
router = APIRouter(prefix="/pv", responses=PV_ERROR_RESPONSES)
for resource_router in (
    capabilities_router,
    health_router,
    cases_router,
    assessments_router,
    coding_router,
    narratives_router,
    reports_router,
    reconciliation_router,
    attachments_router,
    exports_router,
    dashboards_router,
    audit_router,
):
    router.include_router(resource_router)

__all__ = ["router"]
