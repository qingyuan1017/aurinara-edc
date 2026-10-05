"""Authenticated, sanitized PV/Safety health, readiness, and metrics routes.

These endpoints establish the additive, sanitized observability boundary for
the PV module. They report only module readiness/configuration and bounded,
non-sensitive operational signals; they never expose safety content, prohibited
projected fields, raw coordination payloads, credentials, or internal details
(Requirements 24.2, 16.3, 16.5). Liveness and readiness resolve without I/O so
they return well within the 1-second bound (Requirements 25.1, 25.2). The
metrics endpoint returns PV API latency, error rate, worker job failures,
export failures, and overdue regulatory reports over at least the preceding 5
minutes, refreshed continuously so polling at least every 60 seconds observes
current values (Requirement 25.4).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_pv_permission
from app.core.config import get_settings
from app.models.identity import User
from app.services.pv_observability_service import pv_observability_service

router = APIRouter(tags=["pv-health"])
PVHealthGuard = Annotated[User, Depends(require_pv_permission("safety_audit.read"))]


@router.get("/health", response_model=dict[str, object])
async def pv_health(current_user: PVHealthGuard) -> dict[str, object]:
    """Return sanitized PV liveness and module readiness metadata.

    Liveness reports Healthy whenever the service process can accept the
    request; reporting reaches this handler only when the process is live, so
    the status is always ``Healthy`` here (Requirement 25.1). No safety content
    is disclosed.
    """

    settings = get_settings()
    return {
        "module": "PV",
        "status": "Healthy",
        "enabled": settings.pv_enabled and settings.pv_phase != 0,
        "phase": settings.pv_phase,
        "worker_enabled": settings.pv_worker_enabled,
    }


@router.get("/ready", response_model=dict[str, object])
async def pv_ready(current_user: PVHealthGuard) -> dict[str, object]:
    """Return sanitized PV readiness (Requirement 25.2).

    Readiness reports ``Ready`` unless a required configured PV dependency is
    unavailable, in which case it reports ``Not Ready``. The check performs no
    I/O so it resolves within the 1-second bound and discloses no safety
    content.
    """

    settings = get_settings()
    ready = pv_observability_service.is_ready()
    return {
        "module": "PV",
        "status": "Ready" if ready else "Not Ready",
        "enabled": settings.pv_enabled and settings.pv_phase != 0,
        "phase": settings.pv_phase,
    }


@router.get("/metrics", response_model=dict[str, object])
async def pv_metrics(current_user: PVHealthGuard) -> dict[str, object]:
    """Return sanitized PV operational metrics without disclosing safety content.

    The response carries module readiness/configuration flags plus bounded
    operational signals over at least the preceding 5 minutes: PV API latency,
    error rate, worker job failures, export failures, and overdue regulatory
    reports (Requirement 25.4). It never exposes safety data, prohibited
    projected fields, raw coordination payloads, credentials, or internal
    details (Requirements 24.2, 16.3, 16.5).
    """

    settings = get_settings()
    return {
        "module": "PV",
        "enabled": settings.pv_enabled and settings.pv_phase != 0,
        "phase": settings.pv_phase,
        "worker_enabled": settings.pv_worker_enabled,
        "ai_enabled": settings.ai_assistant_enabled and settings.pv_ai_enabled,
        **pv_observability_service.metrics_snapshot(),
    }
