"""CTMS server capability metadata endpoint."""

from fastapi import APIRouter

from app.core.capabilities import get_ctms_capability_manifest
from app.core.config import get_settings

router = APIRouter(tags=["ctms"])


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    """Return phase-gated CTMS and safe platform capability metadata."""

    settings = get_settings()
    manifest = get_ctms_capability_manifest(settings).as_dict()
    manifest["environment"] = settings.environment_metadata
    manifest["platform_capabilities"] = {
        "health_observability": True,
        "structured_logging": True,
        "distributed_tracing": True,
        "isolated_environment": True,
        "optional_ai": settings.ai_assistant_enabled,
        "ctms_ai": settings.ai_assistant_enabled and settings.ctms_ai_enabled,
    }
    return manifest
