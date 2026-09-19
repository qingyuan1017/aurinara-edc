"""Server-side feature capability accessors."""

from app.core.config import Settings
from app.core.ctms import CapabilityManifest, build_ctms_manifest


def get_ctms_capability_manifest(settings: Settings) -> CapabilityManifest:
    """Return CTMS capabilities for the configured phase.

    Disabling the flag only changes advertised availability. It does not remove
    CTMS records and does not alter any EDC route or clinical authority.
    """

    return build_ctms_manifest(
        enabled=settings.ctms_enabled,
        phase=settings.ctms_phase,
    )
