"""Server-side feature capability accessors."""

from app.core.config import Settings
from app.core.ctms import CapabilityManifest, build_ctms_manifest
from app.core.pv import CapabilityManifest as PVCapabilityManifest
from app.core.pv import build_pv_manifest


def get_ctms_capability_manifest(settings: Settings) -> CapabilityManifest:
    """Return CTMS capabilities for the configured phase.

    Disabling the flag only changes advertised availability. It does not remove
    CTMS records and does not alter any EDC route or clinical authority.
    """

    return build_ctms_manifest(
        enabled=settings.ctms_enabled,
        phase=settings.ctms_phase,
    )


def get_pv_capability_manifest(settings: Settings) -> PVCapabilityManifest:
    """Return PV/Safety capabilities for the configured phase.

    Disabling the flag only changes advertised availability. It does not remove
    PV safety records and does not alter any EDC or CTMS route or authority.
    """

    return build_pv_manifest(
        enabled=settings.pv_enabled,
        phase=settings.pv_phase,
    )
