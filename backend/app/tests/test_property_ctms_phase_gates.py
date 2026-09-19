"""Property 22: phased delivery preserves the CTMS/EDC ownership boundary.

# Feature: ctms-integration, Property 22: Phase gates preserve the ownership boundary

**Validates: Requirements 14.1-14.10**

The generated boundary is deliberately deterministic and in-memory.  It uses
server-owned phase manifests, the shared PermissionService, canonical CTMS
identity objects, and the real CTMS clinical pre-mutation guard.  The model
records only CTMS-side writes and audit events; EDC-owned state is snapshotted
before and after every phase attempt to prove that phase enablement cannot
become a clinical write path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ctms import CTMSPhase, Module, build_ctms_manifest
from app.core.exceptions import AuthenticationError, AuthorizationError, ValidationError
from app.models.identity import UserStatus
from app.services.ctms_identity_service import CanonicalEntityType, CanonicalIdentity
from app.services.ctms_ownership_guard import (
    COMPETING_CLINICAL_OPERATIONS,
    CTMSOwnershipError,
    assert_ctms_command_safe,
)
from app.services.permission_service import PermissionService


@dataclass(frozen=True)
class PhaseOperation:
    """One generated CTMS operation and the phase that introduces it."""

    capability: str
    introduced_in: int
    permission: str
    operation: str
    identity_mode: str
    clinical_attempt: bool
    actor_id: UUID
    study_id: UUID
    site_id: UUID
    correlation_id: str


@dataclass(frozen=True)
class PhaseScenario:
    """Generated phase deployment and attempted operation."""

    enabled: bool
    enabled_phase: int
    operation: PhaseOperation
    permission_granted: bool
    scope_mode: str


@dataclass
class _Boundary:
    """Small model of the shared platform boundary around CTMS writes."""

    canonical_identity: CanonicalIdentity
    edc_state: dict[str, str]
    ctms_writes: list[dict[str, object]] = field(default_factory=list)
    audit_events: list[dict[str, object]] = field(default_factory=list)

    def snapshot_edc(self) -> dict[str, str]:
        return dict(self.edc_state)

    def attempt(
        self,
        manifest,
        operation: PhaseOperation,
        *,
        permission_granted: bool,
        scope_mode: str,
    ) -> str:
        """Attempt one write, applying safeguards in production request order."""

        edc_before = self.snapshot_edc()
        payload: dict[str, object] = {
            "study_id": operation.study_id,
            "site_id": operation.site_id,
            "source_identifier": operation.identity_mode,
        }
        if operation.clinical_attempt:
            payload["clinical_data"] = "must-remain-edc-owned"

        # The ownership guard runs before phase/permission checks for any
        # clinical-looking command, so a future phase can never bypass EDC
        # authority by merely advertising a new capability.
        if operation.clinical_attempt:
            with pytest.raises(CTMSOwnershipError):
                assert_ctms_command_safe(
                    payload,
                    operation=operation.operation,
                )
            assert self.snapshot_edc() == edc_before
            assert self.ctms_writes == []
            assert self.audit_events == []
            return "ownership_denied"

        # Canonical references are immutable source identities.  A display
        # label or unknown reference is never accepted as a CTMS identity.
        if operation.identity_mode != "canonical":
            with pytest.raises(ValidationError):
                self._require_canonical_reference(operation)
            assert self.snapshot_edc() == edc_before
            assert self.ctms_writes == []
            assert self.audit_events == []
            return "identity_denied"
        self._require_canonical_reference(operation)

        if not manifest.supports(operation.capability):
            assert self.snapshot_edc() == edc_before
            assert self.ctms_writes == []
            assert self.audit_events == []
            return "phase_denied"

        user = self._user(operation, permission_granted=permission_granted, scope_mode=scope_mode)
        try:
            PermissionService().require(
                user,
                operation.permission,
                study_id=operation.study_id,
                site_id=operation.site_id,
            )
        except (AuthenticationError, AuthorizationError):
            assert self.snapshot_edc() == edc_before
            assert self.ctms_writes == []
            assert self.audit_events == []
            return "authorization_denied"

        # This is the final pre-mutation check.  Canonical *_id references are
        # allowed; all EDC-owned fields/operations remain prohibited.
        assert_ctms_command_safe(payload, operation=operation.operation)
        self.ctms_writes.append(
            {
                "capability": operation.capability,
                "module": Module.CTMS.value,
                "source_identifier": self.canonical_identity.source_identifier,
                "study_id": operation.study_id,
                "site_id": operation.site_id,
            }
        )
        self.audit_events.append(
            {
                "module": Module.CTMS.value,
                "actor_id": operation.actor_id,
                "action": operation.operation,
                "scope": {"study_id": operation.study_id, "site_id": operation.site_id},
                "source_record_id": self.canonical_identity.source_identifier,
                "correlation_id": operation.correlation_id,
            }
        )
        assert self.snapshot_edc() == edc_before
        return "written"

    def _require_canonical_reference(self, operation: PhaseOperation) -> None:
        if operation.identity_mode != "canonical":
            raise ValidationError(
                "CTMS references must use a canonical stable identifier",
                {"reason": "DISPLAY_NAME_NOT_ALLOWED"},
            )
        if operation.study_id != self.canonical_identity.source_identifier:
            raise ValidationError(
                "CTMS reference does not resolve to the canonical EDC identity",
                {"reason": "RECORD_NOT_FOUND"},
            )

    @staticmethod
    def _user(
        operation: PhaseOperation,
        *,
        permission_granted: bool,
        scope_mode: str,
    ) -> SimpleNamespace:
        permission = operation.permission if permission_granted else "ctms.unrelated-permission"
        if scope_mode == "system":
            assigned_study = None
            assigned_site = None
        elif scope_mode == "study":
            assigned_study = operation.study_id
            assigned_site = None
        elif scope_mode == "site":
            assigned_study = operation.study_id
            assigned_site = operation.site_id
        else:
            assigned_study = uuid4()
            assigned_site = uuid4()

        role_permission = SimpleNamespace(permission=SimpleNamespace(code=permission))
        role = SimpleNamespace(role_permissions=[role_permission])
        user_role = SimpleNamespace(role=role, study_id=assigned_study, site_id=assigned_site)
        return SimpleNamespace(
            id=operation.actor_id,
            status=UserStatus.active,
            user_roles=[user_role],
        )


_OPERATION_SPECS: tuple[tuple[str, int, str, str], ...] = (
    ("canonical_study_references", 1, "ctms.operational-data-read", "link_study"),
    ("canonical_site_references", 1, "ctms.operational-data-read", "link_site"),
    ("operational_studies", 1, "ctms.operational-study-management", "update_operational_study"),
    ("operational_sites", 1, "ctms.operational-site-management", "update_operational_site"),
    ("enrollment_planning", 1, "ctms.enrollment-management", "update_enrollment_plan"),
    ("operational_milestones", 1, "ctms.enrollment-management", "record_operational_milestone"),
    ("operational_dashboards", 1, "ctms.operational-data-read", "refresh_operational_dashboard"),
    ("monitoring", 2, "ctms.monitoring-activity-management", "schedule_monitoring_activity"),
    ("operational_tasks", 2, "ctms.operational-study-management", "update_operational_task"),
    ("operational_contacts", 2, "ctms.operational-study-management", "update_operational_contact"),
    ("operational_attachments", 2, "ctms.operational-study-management", "upload_operational_attachment"),
    ("ctms_operational_projections", 2, "ctms.operational-data-read", "refresh_operational_projection"),
    ("coordination_events", 2, "ctms.operational-data-read", "accept_coordination_event"),
    ("notifications", 2, "ctms.operational-data-read", "mark_notification_read"),
    ("approved_query_summaries", 3, "ctms.operational-data-read", "refresh_query_summary"),
    ("data_quality_signals", 3, "ctms.operational-data-read", "refresh_data_quality_signal"),
    ("coordination_retries", 3, "ctms.coordination-replay", "retry_coordination_event"),
    ("failed_events", 3, "ctms.coordination-replay", "replay_failed_event"),
    ("coordination_conflicts", 3, "ctms.conflict-management", "resolve_coordination_conflict"),
    ("advanced_operational_reports", 3, "ctms.operational-data-read", "run_advanced_report"),
    ("operational_exports", 3, "ctms.operational-data-read", "create_operational_export"),
    ("qualification_evidence", 3, "ctms.operational-data-read", "record_qualification_evidence"),
)


@st.composite
def phase_scenarios(draw: st.DrawFn) -> PhaseScenario:
    """Generate enabled manifests, phase operations, identities, and scopes."""

    capability, introduced_in, permission, operation = draw(st.sampled_from(_OPERATION_SPECS))
    actor_id = draw(st.uuids(version=4))
    study_id = draw(st.uuids(version=4))
    site_id = draw(st.uuids(version=4))
    return PhaseScenario(
        enabled=draw(st.booleans()),
        enabled_phase=draw(st.integers(min_value=0, max_value=3)),
        operation=PhaseOperation(
            capability=capability,
            introduced_in=introduced_in,
            permission=permission,
            operation=operation,
            identity_mode=draw(st.sampled_from(("canonical", "display_name", "unknown"))),
            clinical_attempt=draw(st.booleans()),
            actor_id=actor_id,
            study_id=study_id,
            site_id=site_id,
            correlation_id=draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=24)),
        ),
        permission_granted=draw(st.booleans()),
        scope_mode=draw(st.sampled_from(("system", "study", "site", "out_of_scope"))),
    )


@given(scenario=phase_scenarios())
@settings(max_examples=100, deadline=None, derandomize=True)
def test_phase_gates_preserve_shared_safeguards_and_edc_ownership(
    scenario: PhaseScenario,
) -> None:
    """Phase enablement changes CTMS availability, never shared safeguards."""

    operation = scenario.operation
    boundary = _Boundary(
        canonical_identity=CanonicalIdentity(CanonicalEntityType.STUDY, operation.study_id),
        edc_state={
            "study_version": "edc-study-version",
            "subject_identity": "edc-subject",
            "visit_instance": "edc-visit",
            "clinical_data": "edc-clinical-data",
            "query": "edc-query",
            "clinical_export": "edc-clinical-export",
        },
    )
    edc_before_all_phases = boundary.snapshot_edc()

    manifests = [
        build_ctms_manifest(enabled=scenario.enabled, phase=phase)
        for phase in range(0, 4)
    ]
    for phase, manifest in enumerate(manifests):
        # The manifest is cumulative and server-owned.  Enabling a later phase
        # cannot remove an earlier capability or advertise capabilities while
        # CTMS is disabled.
        assert manifest.module is Module.CTMS
        expected_enabled = scenario.enabled and phase != CTMSPhase.DISABLED
        assert manifest.enabled is expected_enabled
        if manifest.enabled:
            assert manifest.phase.value == phase
            # Earlier capabilities are a subset of the later manifest.
            assert all(
                manifest.supports(capability)
                for capability in manifests[phase - 1].capabilities
            ) if phase > 1 else True
            for required in ("canonical_study_references", "canonical_site_references", "scoped_authorization", "shared_audit"):
                assert manifest.supports(required)
        else:
            assert manifest.capabilities == ()

        # Use a fresh boundary for every phase so the before/after comparison
        # is independent of operation ordering and captures each gate itself.
        phase_boundary = _Boundary(
            canonical_identity=boundary.canonical_identity,
            edc_state=boundary.snapshot_edc(),
        )
        result = phase_boundary.attempt(
            manifest,
            operation,
            permission_granted=scenario.permission_granted,
            scope_mode=scenario.scope_mode,
        )

        can_write = (
            not operation.clinical_attempt
            and operation.identity_mode == "canonical"
            and manifest.supports(operation.capability)
            and scenario.permission_granted
            and scenario.scope_mode in {"system", "study", "site"}
        )
        assert (result == "written") is can_write
        if can_write:
            assert len(phase_boundary.ctms_writes) == 1
            assert len(phase_boundary.audit_events) == 1
            audit = phase_boundary.audit_events[0]
            assert audit["module"] == Module.CTMS.value
            assert audit["source_record_id"] == operation.study_id
            assert audit["correlation_id"] == operation.correlation_id
            assert audit["scope"] == {"study_id": operation.study_id, "site_id": operation.site_id}
        else:
            assert phase_boundary.ctms_writes == []
            assert phase_boundary.audit_events == []
        assert phase_boundary.snapshot_edc() == edc_before_all_phases

    # The EDC ownership list is independent of phase; every representative
    # clinical operation remains rejected even at the final enabled phase.
    for operation_name in sorted(COMPETING_CLINICAL_OPERATIONS):
        clinical = PhaseOperation(
            capability=operation.capability,
            introduced_in=operation.introduced_in,
            permission=operation.permission,
            operation=operation_name,
            identity_mode="canonical",
            clinical_attempt=True,
            actor_id=operation.actor_id,
            study_id=operation.study_id,
            site_id=operation.site_id,
            correlation_id=operation.correlation_id,
        )
        final_boundary = _Boundary(
            canonical_identity=boundary.canonical_identity,
            edc_state=boundary.snapshot_edc(),
        )
        result = final_boundary.attempt(
            build_ctms_manifest(enabled=True, phase=CTMSPhase.PHASE_3),
            clinical,
            permission_granted=True,
            scope_mode="system",
        )
        assert result == "ownership_denied"
        assert final_boundary.snapshot_edc() == edc_before_all_phases
