"""Shared PV/Safety module identifiers, value types, and phased capabilities.

This module contains platform-level contracts only. PV-owned safety records
belong in ``app.models.pv`` and must reference canonical Study/Site identity and
the EDC Subject_Reference/Visit_Instance identity rather than recreating any EDC
clinical record or CTMS operational record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final, NewType
from uuid import UUID


class Module(StrEnum):
    """First-party module owning a persisted field or operational capability.

    PV is a third co-equal module alongside EDC and CTMS. It never becomes a
    competing clinical or operational authority.
    """

    EDC = "EDC"
    CTMS = "CTMS"
    PV = "PV"


class CaseState(StrEnum):
    """Constrained Safety_Case lifecycle states.

    The legal transitions between these states are owned by the safety case
    service; the enum only names the states themselves.
    """

    OPEN = "Open"
    IN_REVIEW = "In Review"
    FOLLOW_UP_REQUIRED = "Follow-up Required"
    READY_TO_REPORT = "Ready to Report"
    REPORTED = "Reported"
    CLOSED = "Closed"
    REOPENED = "Reopened"


class ReportStatus(StrEnum):
    """Regulatory_Report status values."""

    PENDING = "Pending"
    SUBMITTED = "Submitted"
    ACKNOWLEDGED = "Acknowledged"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class PVPhase(IntEnum):
    """Incremental PV delivery phases; zero means the module is disabled."""

    DISABLED = 0
    PHASE_1 = 1
    PHASE_2 = 2
    PHASE_3 = 3


CorrelationIdentifier = NewType("CorrelationIdentifier", str)
IdempotencyKey = NewType("IdempotencyKey", str)
# Glossary-compatible aliases for code that uses the specification's names.
Correlation_Identifier = CorrelationIdentifier
Idempotency_Key = IdempotencyKey

UTCDateTime = datetime


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Immutable request-scoped actor and correlation context.

    Every PV service method receives this context so audit events, logs, and
    coordination records share the same request and correlation identifiers.
    """

    user_id: UUID
    request_id: str
    correlation_id: CorrelationIdentifier


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted and API-facing records."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Validate and normalize a timestamp to UTC.

    Naive timestamps are rejected so local time cannot enter a safety record by
    accident. Offset-aware timestamps are normalized without losing the instant.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include timezone information")
    return value.astimezone(UTC)


_PHASE_CAPABILITIES: Final[Mapping[PVPhase, tuple[str, ...]]] = MappingProxyType(
    {
        PVPhase.DISABLED: (),
        PVPhase.PHASE_1: (
            "canonical_study_references",
            "canonical_site_references",
            "subject_references",
            "safety_case_intake",
            "adverse_event_capture",
            "case_lifecycle",
            "case_versions",
            "seriousness_assessment",
            "pv_roles",
            "scoped_authorization",
            "shared_audit",
            "safety_exports",
        ),
        PVPhase.PHASE_2: (
            "canonical_study_references",
            "canonical_site_references",
            "subject_references",
            "safety_case_intake",
            "adverse_event_capture",
            "case_lifecycle",
            "case_versions",
            "seriousness_assessment",
            "pv_roles",
            "scoped_authorization",
            "shared_audit",
            "safety_exports",
            "meddra_coding",
            "whodrug_coding",
            "causality_assessment",
            "expectedness_assessment",
            "severity_grade",
            "case_narratives",
            "edc_ae_reconciliation",
            "safety_operational_projection",
            "coordination_events",
            "safety_notifications",
            "safety_attachments",
        ),
        PVPhase.PHASE_3: (
            "canonical_study_references",
            "canonical_site_references",
            "subject_references",
            "safety_case_intake",
            "adverse_event_capture",
            "case_lifecycle",
            "case_versions",
            "seriousness_assessment",
            "pv_roles",
            "scoped_authorization",
            "shared_audit",
            "safety_exports",
            "meddra_coding",
            "whodrug_coding",
            "causality_assessment",
            "expectedness_assessment",
            "severity_grade",
            "case_narratives",
            "edc_ae_reconciliation",
            "safety_operational_projection",
            "coordination_events",
            "safety_notifications",
            "safety_attachments",
            "regulatory_reporting",
            "regulatory_clocks",
            "icsr_e2b",
            "advanced_safety_exports",
            "safety_dashboards",
            "qualification_evidence",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Server-owned, serializable description of the PV module's capabilities."""

    module: Module
    enabled: bool
    phase: PVPhase
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


def build_pv_manifest(*, enabled: bool, phase: int) -> CapabilityManifest:
    """Build a PV manifest without changing or deleting any persisted data.

    Disabling PV only changes advertised availability. It never removes PV
    safety data and never alters any EDC or CTMS route or authority.
    """

    try:
        selected_phase = PVPhase(phase)
    except ValueError as exc:
        raise ValueError("PV phase must be one of 0, 1, 2, or 3") from exc

    active = enabled and selected_phase is not PVPhase.DISABLED
    return CapabilityManifest(
        module=Module.PV,
        enabled=active,
        phase=selected_phase,
        capabilities=_PHASE_CAPABILITIES[selected_phase] if active else (),
    )


PV_MODULE_PACKAGE = "app.models.pv"

__all__ = [
    "PV_MODULE_PACKAGE",
    "ActorContext",
    "CapabilityManifest",
    "CaseState",
    "CorrelationIdentifier",
    "Correlation_Identifier",
    "IdempotencyKey",
    "Idempotency_Key",
    "Module",
    "PVPhase",
    "ReportStatus",
    "UTCDateTime",
    "build_pv_manifest",
    "ensure_utc",
    "utc_now",
]
