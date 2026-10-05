"""PV/Safety server capability metadata endpoint."""

from fastapi import APIRouter

from app.core.capabilities import get_pv_capability_manifest
from app.core.config import get_settings

router = APIRouter(tags=["pv"])


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    """Return phase-gated PV and safe platform capability metadata.

    Disabling PV only hides PV navigation and operations; it never deletes PV
    safety data and never alters EDC/CTMS routes or authority.
    """

    settings = get_settings()
    manifest = get_pv_capability_manifest(settings).as_dict()
    manifest["environment"] = settings.environment_metadata
    manifest["platform_capabilities"] = {
        "health_observability": True,
        "structured_logging": True,
        "distributed_tracing": True,
        "isolated_environment": True,
        "optional_ai": settings.ai_assistant_enabled,
        "pv_ai": settings.ai_assistant_enabled and settings.pv_ai_enabled,
    }
    return manifest
