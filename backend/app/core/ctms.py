"""Shared CTMS module identifiers and phased capability metadata.

This module contains platform-level contracts only. CTMS-owned records belong in
``app.models.ctms`` and must reference EDC clinical identities rather than
recreating them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final, NewType


class Module(StrEnum):
    """First-party module owning a persisted field or operational capability."""

    EDC = "EDC"
    CTMS = "CTMS"
    # PV is a third co-equal module. It is listed here so the shared platform
    # primitives (audit content owner, optional AI controls) can name the PV
    # module without forking a second enum. PV-owned safety records still live
    # under ``app.models.pv`` and never carry EDC clinical or CTMS operational
    # authority.
    PV = "PV"


class OwnershipState(StrEnum):
    """State of a field or record relative to its authoritative owner."""

    AUTHORITATIVE = "authoritative"
    PROJECTED = "projected"
    COORDINATED = "coordinated"
    ARCHIVED = "archived"


class CTMSPhase(IntEnum):
    """Incremental CTMS delivery phases; zero means the module is disabled."""

    DISABLED = 0
    PHASE_1 = 1
    PHASE_2 = 2
    PHASE_3 = 3


CorrelationIdentifier = NewType("CorrelationIdentifier", str)
IdempotencyKey = NewType("IdempotencyKey", str)
# Glossary-compatible aliases for code that uses the specification's names.
Correlation_Identifier = CorrelationIdentifier
Idempotency_Key = IdempotencyKey


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted and API-facing records."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Validate and normalize a timestamp to UTC.

    Naive timestamps are rejected so local time cannot enter a CTMS record by
    accident. Offset-aware timestamps are normalized without losing the instant.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include timezone information")
    return value.astimezone(UTC)


UTCDateTime = datetime


_PHASE_CAPABILITIES: Final[Mapping[CTMSPhase, tuple[str, ...]]] = MappingProxyType(
    {
        CTMSPhase.DISABLED: (),
        CTMSPhase.PHASE_1: (
            "canonical_study_references",
            "canonical_site_references",
            "operational_studies",
            "operational_sites",
            "enrollment_planning",
            "operational_milestones",
            "ctms_roles",
            "scoped_authorization",
            "shared_audit",
            "operational_dashboards",
        ),
        CTMSPhase.PHASE_2: (
            "canonical_study_references",
            "canonical_site_references",
            "operational_studies",
            "operational_sites",
            "enrollment_planning",
            "operational_milestones",
            "ctms_roles",
            "scoped_authorization",
            "shared_audit",
            "operational_dashboards",
            "monitoring",
            "operational_tasks",
            "operational_contacts",
            "operational_attachments",
            "ctms_operational_projections",
            "coordination_events",
            "notifications",
        ),
        CTMSPhase.PHASE_3: (
            "canonical_study_references",
            "canonical_site_references",
            "operational_studies",
            "operational_sites",
            "enrollment_planning",
            "operational_milestones",
            "ctms_roles",
            "scoped_authorization",
            "shared_audit",
            "operational_dashboards",
            "monitoring",
            "operational_tasks",
            "operational_contacts",
            "operational_attachments",
            "ctms_operational_projections",
            "coordination_events",
            "notifications",
            "approved_query_summaries",
            "data_quality_signals",
            "coordination_retries",
            "failed_events",
            "coordination_conflicts",
            "advanced_operational_reports",
            "operational_exports",
            "qualification_evidence",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Server-owned, serializable description of one module's capabilities."""

    module: Module
    enabled: bool
    phase: CTMSPhase
    capabilities: tuple[str, ...]

    def supports(self, capability: str) -> bool:
        """Return whether a capability is enabled in the active delivery phase."""

        return self.enabled and capability in self.capabilities

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation used by the API and frontend."""

        return {
            "module": self.module.value,
            "enabled": self.enabled,
            "phase": self.phase.value,
            "capabilities": list(self.capabilities),
        }


def build_ctms_manifest(*, enabled: bool, phase: int) -> CapabilityManifest:
    """Build a CTMS manifest without changing or deleting any persisted data."""

    try:
        selected_phase = CTMSPhase(phase)
    except ValueError as exc:
        raise ValueError("CTMS phase must be one of 0, 1, 2, or 3") from exc

    active = enabled and selected_phase is not CTMSPhase.DISABLED
    return CapabilityManifest(
        module=Module.CTMS,
        enabled=active,
        phase=selected_phase,
        capabilities=_PHASE_CAPABILITIES[selected_phase] if active else (),
    )
