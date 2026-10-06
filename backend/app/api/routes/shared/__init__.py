"""Versioned shared/cross-cutting API route package.

Aggregates cross-cutting resource routers (health, auth, users, files,
notifications, audit, and the global AI assistant) into a single ``router``
mounted below ``/api/v1``. The aggregate adds no prefix of its own, so each
resource router keeps the exact path prefix it declares. These routes are
shared platform infrastructure consumed by EDC, CTMS, and PV alike.
"""

from fastapi import APIRouter

from app.api.routes.shared.ai_assistant import router as ai_assistant_router
from app.api.routes.shared.audit import fields_audit_router, subjects_audit_router
from app.api.routes.shared.audit import router as audit_router
from app.api.routes.shared.auth import router as auth_router
from app.api.routes.shared.files import router as files_router
from app.api.routes.shared.health import router as health_router
from app.api.routes.shared.notifications import router as notifications_router
from app.api.routes.shared.users import router as users_router

# Mounted without an added prefix so each resource router keeps its own path.
router = APIRouter()
for resource_router in (
    health_router,
    ai_assistant_router,
    auth_router,
    users_router,
    files_router,
    notifications_router,
    audit_router,
    subjects_audit_router,
    fields_audit_router,
):
    router.include_router(resource_router)

__all__ = ["router"]
