"""PV compliance and environment-management controls (Requirement 20).

This module is platform-level and side-effect free. It provides:

* :data:`PV_TRACEABILITY_MATRIX` and :func:`build_traceability_matrix` mapping
  each PV requirement to its design reference and qualification test
  (Requirement 20.4).
* :data:`PV_DISTINCT_CASE_STATES` and :func:`case_states_are_distinct` asserting
  Open/In Review/Ready to Report/Reported/Closed are distinct states
  (Requirement 20.5).
* :func:`clock_agreement_within_tolerance` for the 5-second server-clock
  agreement bound on PV safety Audit_Event timestamps (Requirement 20.2).
* :func:`build_environment_controls` summarizing per-Environment isolation,
  retention floor, and backup/restore targets from settings (Requirements 20.1,
  20.3), exposing only non-secret metadata.

No function here reads another Environment's database, object storage, secrets,
authentication configuration, or logs; PV relies on the shared, per-Environment
:class:`app.core.config.Settings` isolation and only surfaces PV feature flags
and safety settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings, get_settings
from app.core.pv import CaseState, ensure_utc

# The five distinct Safety_Case states named by Requirement 20.5. The lifecycle
# also models the transitional ``Follow-up Required`` and ``Reopened`` states,
# but these five are the compliance-required distinct states.
PV_DISTINCT_CASE_STATES: tuple[CaseState, ...] = (
    CaseState.OPEN,
    CaseState.IN_REVIEW,
    CaseState.READY_TO_REPORT,
    CaseState.REPORTED,
    CaseState.CLOSED,
)


@dataclass(frozen=True, slots=True)
class TraceabilityEntry:
    """One row of the PV Traceability_Matrix."""

    requirement: str
    design_reference: str
    qualification_test: str

    def as_dict(self) -> dict[str, str]:
        return {
            "requirement": self.requirement,
            "design_reference": self.design_reference,
            "qualification_test": self.qualification_test,
        }


# Requirement -> design reference -> primary qualification test. Mirrors the
# design "Requirements traceability" table so each PV requirement is traceable
# to a design section and a qualification test (Requirement 20.4).
PV_TRACEABILITY_MATRIX: tuple[TraceabilityEntry, ...] = (
    TraceabilityEntry("1. Shared authentication and session reuse", "Auth_Service reuse; scope resolved before any Safety_Data op", "Property 5; auth integration/security tests"),
    TraceabilityEntry("2. Authorization and permission enforcement", "Permission_Service route/object checks; PV safety roles", "Property 5; direct API permission tests"),
    TraceabilityEntry("3. Safety case intake and capture", "Safety_Case_Service; pv_safety_cases/pv_adverse_event_records; canonical reference integrity", "Properties 1, 3; intake validation and reference tests"),
    TraceabilityEntry("4. Safety case lifecycle and versioning", "Case state machine; pv_case_versions sequencing and immutability", "Property 2; lifecycle and version-immutability tests"),
    TraceabilityEntry("5. Safety assessments", "Assessment_Service; seriousness criteria; Closed-case rejection", "Property 3; assessment validation/preservation tests"),
    TraceabilityEntry("6. MedDRA and WHODrug coding", "Coding_Service; dictionary-version retention; recoding traceability", "Property 3; coding retention/immutability tests"),
    TraceabilityEntry("7. Case narratives", "Narrative_Service; versioned narratives; reason bounds", "Property 3; narrative versioning tests"),
    TraceabilityEntry("8. Regulatory reporting and expedited timelines", "Regulatory_Reporting_Service; reportability rules; Regulatory_Clock; report state machine", "Properties 2, 7; clock computation and transition tests"),
    TraceabilityEntry("9. ICSR and E2B message handling", "produce_e2b/parse_e2b; mandatory-field validation; round-trip", "Property 8; round-trip and invalid-message tests"),
    TraceabilityEntry("10. EDC adverse-event reconciliation", "Reconciliation_Service; read-only projection; pure diff; no EDC mutation", "Properties 1, 6; reconciliation diffing and boundary tests"),
    TraceabilityEntry("11. PV safety audit trail", "Audit_Service PV content; same-transaction atomicity; immutability; scoped ordered search/export", "Properties 4, 5, 6; audit atomicity/immutability/ordering tests"),
    TraceabilityEntry("12. Safety data export", "Shared Export_Service; job lifecycle; filters; format allowlist; scoped content", "Properties 5, 6; export lifecycle and content tests"),
    TraceabilityEntry("13. Safety dashboards and reports", "Dashboard_Service PV metrics; compliance buckets; read-only projections", "Properties 6, 7; dashboard scope-consistency tests"),
    TraceabilityEntry("14. Safety notifications", "Notification_Service triggers; status machine; dedup", "Property 2; notification status and dedup tests"),
    TraceabilityEntry("15. Safety file attachments", "File_Attachment_Service Safety_Attachment; access control; soft delete; Closed-case rejection", "Property 6; attachment access and storage-failure tests"),
    TraceabilityEntry("16. Shared API layer standards", "/api/v1/pv; pagination envelope; error envelope; request-id propagation; same-transaction audit", "Properties 4, 5, 6, 8; API contract and non-leak tests"),
    TraceabilityEntry("17. Database and persistence", "pv_ tables; UUID PKs; UTC; global-unique id; indexes; correlation refs; soft deletion", "Property 1; migration/constraint/index tests"),
    TraceabilityEntry("18. Backend architecture and coding rules", "Thin routes; repository-only DB access; atomic data+audit; permission before mutation", "Properties 3, 4, 5; architecture/lint and atomicity tests"),
    TraceabilityEntry("19. Frontend safety application", "Permission-aware PV routes; consistent labels; Zod; disabled Closed controls; history dialogs", "Property 5; Vitest/Playwright tests"),
    TraceabilityEntry("20. Compliance, validation, environment", "Environment isolation; UTC clock agreement; retention/backup; traceability matrix; state distinctness", "Property 4; environment/compliance integration and smoke tests"),
    TraceabilityEntry("21. PV phased delivery and testing", "Phase gates; automated suites; EDC/CTMS excluded from PV deliverables", "All properties; phase qualification and CI evidence"),
    TraceabilityEntry("22. Optional AI assistant", "PV-scoped AI_Assistant_Service; scope check; human confirmation; AI-assisted audit origin", "Properties 4, 5; AI streaming/scope/confirmation integration tests"),
    TraceabilityEntry("23. Unified platform safety ownership and coordination", "Ownership uniqueness; canonical identity; minimized read-only projections; independent resilience", "Properties 1, 5, 6; ownership-boundary and resilience tests"),
    TraceabilityEntry("24. Performance", "Bounded pagination; async job handoff; concurrency target", "Property 5 (pagination); load/benchmark tests"),
    TraceabilityEntry("25. Reliability and observability", "Liveness/readiness; structured logs; metrics endpoint", "Integration/smoke tests for health/metrics/logs"),
)


def build_traceability_matrix() -> tuple[TraceabilityEntry, ...]:
    """Return the PV Traceability_Matrix (Requirement 20.4)."""

    return PV_TRACEABILITY_MATRIX


def case_states_are_distinct() -> bool:
    """Return whether the compliance-required Safety_Case states are distinct."""

    values = [state.value for state in PV_DISTINCT_CASE_STATES]
    return len(values) == len(set(values))


def clock_agreement_within_tolerance(
    first: datetime,
    second: datetime,
    *,
    tolerance_seconds: int | None = None,
    settings: Settings | None = None,
) -> bool:
    """Return whether two server-derived UTC timestamps agree within tolerance.

    PV safety Audit_Event timestamps are derived from the server clock and stored
    as UTC; participating services must agree within a bounded skew (Requirement
    20.2). Naive timestamps are rejected so local time cannot enter the check.
    """

    resolved = settings or get_settings()
    tolerance = (
        tolerance_seconds
        if tolerance_seconds is not None
        else resolved.pv_clock_skew_tolerance_seconds
    )
    delta = abs((ensure_utc(first) - ensure_utc(second)).total_seconds())
    return delta <= tolerance


def build_environment_controls(settings: Settings | None = None) -> dict[str, object]:
    """Summarize PV environment isolation, retention, and backup/restore controls.

    Returns only non-secret metadata. PV reuses the shared per-Environment
    isolation of database, object storage, secrets, authentication
    configuration, and logging (Requirement 20.1); retention floor is at least
    seven years and backup/restore targets are at most 24 hours between backups
    and a 4-hour restore window (Requirement 20.3).
    """

    resolved = settings or get_settings()
    return {
        "environment": resolved.pv_environment_metadata,
        "retention": {
            "floor_days": resolved.pv_retention_floor_days,
            "meets_seven_year_minimum": resolved.pv_retention_floor_days >= 2555,
            "batch_size": resolved.pv_retention_batch_size,
        },
        "backup": {
            "enabled": resolved.pv_backup_enabled,
            "interval_hours": resolved.pv_backup_interval_hours,
            "meets_daily_minimum": resolved.pv_backup_interval_hours <= 24,
        },
        "restore": {
            "enabled": resolved.pv_restore_enabled,
            "target_hours": resolved.pv_restore_target_hours,
            "meets_four_hour_target": resolved.pv_restore_target_hours <= 4,
        },
        "clock": {
            "skew_tolerance_seconds": resolved.pv_clock_skew_tolerance_seconds,
            "meets_five_second_agreement": resolved.pv_clock_skew_tolerance_seconds <= 5,
        },
        "case_states": [state.value for state in PV_DISTINCT_CASE_STATES],
        "case_states_distinct": case_states_are_distinct(),
        "traceability_matrix_size": len(PV_TRACEABILITY_MATRIX),
    }


__all__ = [
    "PV_DISTINCT_CASE_STATES",
    "PV_TRACEABILITY_MATRIX",
    "TraceabilityEntry",
    "build_environment_controls",
    "build_traceability_matrix",
    "case_states_are_distinct",
    "clock_agreement_within_tolerance",
]
