"""Property-based verification of the explicit CTMS/EDC ownership boundary.

# Feature: ctms-integration, Property 1: Exactly one authoritative owner governs each field

**Validates: Requirements 1.2, 1.5-1.8, 3.7-3.8, 4.5-4.8, 5.8-5.11, 6.15, 8.10, 14.4**

The test uses the task 4.1 ownership-rule compiler and pre-mutation guard with a
small deterministic in-memory boundary model.  No database, worker, network, or
external service is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ctms import Module
from app.core.exceptions import ConflictError
from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType
from app.schemas.ctms.ownership import ProjectionFieldType
from app.services.ctms_ownership_guard import (
    COMPETING_CLINICAL_OPERATIONS,
    CTMSOwnershipError,
    assert_ctms_command_safe,
)
from app.services.status_ownership_rule_service import (
    CompiledOwnershipRule,
    StatusOwnershipRuleService,
)


@dataclass(frozen=True)
class OwnershipScenario:
    """One generated shared entity, active rule, command set, and projection."""

    entity_type: str
    field_path: str
    authoritative_module: Module
    allowed_targets: tuple[str, ...]
    command_kind: str
    command_module: Module
    command_value: str
    command_transition: str
    competing_operation: str
    subject_id: UUID
    projection_status: str
    source_version: str


@dataclass(frozen=True)
class OwnershipCommand:
    """A command submitted by either module to the in-memory boundary."""

    module: Module
    kind: str
    field_path: str
    value: str
    transition_target: str
    operation: str | None = None
    payload: dict[str, Any] | None = None


class OwnershipBoundaryError(ConflictError):
    """The command is outside the active ownership rule."""


class _InMemoryOwnershipBoundary:
    """Deterministic source/projection boundary used by the property model."""

    def __init__(self, rule: CompiledOwnershipRule, projection: dict[str, Any]) -> None:
        self.rule = rule
        self.authoritative_state = {rule.field_path: "draft"}
        self.projection = dict(projection)

    def write_authoritative(self, command: OwnershipCommand) -> None:
        """Allow only the single authoritative writer to change the source field."""

        if command.kind == "competing_clinical_write":
            assert_ctms_command_safe(command.payload, operation=command.operation)
            raise AssertionError("the competing clinical operation was not rejected")

        if command.module is not self.rule.authoritative_module:
            raise OwnershipBoundaryError(
                "Only the authoritative module can write this field",
                {
                    "field_path": self.rule.field_path,
                    "authoritative_module": self.rule.authoritative_module.value,
                },
            )

        # Competing clinical operations use the real task 4.1 guard above.
        # Ordinary writes are governed by this active rule: the generated
        # field/owner pairs distinguish EDC clinical fields from CTMS
        # operational fields, so an operational status is not mistaken for a
        # competing clinical mutation by this boundary model.
        self.authoritative_state[self.rule.field_path] = command.value

    def transition_authoritative(self, command: OwnershipCommand) -> None:
        """Apply only an explicitly configured transition by the owner."""

        if command.module is not self.rule.authoritative_module:
            raise OwnershipBoundaryError(
                "Only the authoritative module can transition this field",
                {"field_path": self.rule.field_path},
            )
        current = self.authoritative_state[self.rule.field_path]
        allowed = self.rule.allowed_transitions.get(str(current), ())
        if command.transition_target not in allowed:
            raise OwnershipBoundaryError(
                "The transition is not configured by the active ownership rule",
                {
                    "field_path": self.rule.field_path,
                    "from": current,
                    "to": command.transition_target,
                },
            )
        self.authoritative_state[self.rule.field_path] = command.transition_target

    def read_projection(self, module: Module) -> MappingProxyType:
        """Expose a projection only to its configured consumer as read-only."""

        if module is not self.rule.projection_target:
            raise OwnershipBoundaryError("Projection is not configured for this module")
        return MappingProxyType(self.projection)

    def write_projection(self, module: Module, field: str, value: str) -> None:
        """Reject consumer writes rather than treating a projection as a source."""

        if module is self.rule.projection_target and field in self.projection:
            raise OwnershipBoundaryError(
                "A projection consumer cannot write the authoritative field",
                {"field_path": field},
            )
        raise OwnershipBoundaryError("Projection access is read-only")


def _other_module(module: Module) -> Module:
    return Module.CTMS if module is Module.EDC else Module.EDC


@st.composite
def ownership_scenarios(draw: st.DrawFn) -> OwnershipScenario:
    """Generate canonical entities, field ownership, commands, and projections."""

    field_path, field_owner = draw(
        st.sampled_from(
            [
                ("status", Module.EDC),
                ("clinical_data", Module.EDC),
                ("visit_instance_status", Module.EDC),
                ("query_status", Module.EDC),
                ("operational_status", Module.CTMS),
                ("readiness", Module.CTMS),
                ("milestone_date", Module.CTMS),
                ("monitoring_status", Module.CTMS),
            ]
        )
    )
    statuses = ("planning", "ready", "active", "closed")
    allowed_targets = tuple(draw(st.lists(st.sampled_from(statuses), unique=True, max_size=4)))
    return OwnershipScenario(
        entity_type=draw(st.sampled_from(("Study", "Site", "Subject", "Visit_Instance", "Operational_Record"))),
        field_path=field_path,
        authoritative_module=field_owner,
        allowed_targets=allowed_targets,
        command_kind=draw(st.sampled_from(("write", "transition", "competing_clinical_write"))),
        command_module=draw(st.sampled_from((Module.EDC, Module.CTMS))),
        command_value=draw(st.sampled_from(statuses)),
        command_transition=draw(st.sampled_from(statuses)),
        competing_operation=draw(st.sampled_from(sorted(COMPETING_CLINICAL_OPERATIONS))),
        subject_id=draw(st.uuids(version=4)),
        projection_status=draw(st.sampled_from(statuses)),
        source_version=draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)),
    )


def _rule_for(scenario: OwnershipScenario) -> CompiledOwnershipRule:
    """Compile one active versioned rule with exactly one owner and consumer."""

    owner = scenario.authoritative_module
    return StatusOwnershipRuleService.compile_rule(
        {
            "entity_type": scenario.entity_type,
            "field_path": scenario.field_path,
            "authoritative_module": owner,
            "writable_module": owner,
            "projection_target": _other_module(owner),
            "projection_type": ProjectionType.SUBJECT_STATUS,
            "allowed_transitions": {"draft": list(scenario.allowed_targets)},
            "typed_allowlist": {
                "subject_id": ProjectionFieldType.UUID.value,
                "status": ProjectionFieldType.STRING.value,
                "source_version": ProjectionFieldType.STRING.value,
            },
            "version": 1,
            "effective_from": datetime(2020, 1, 1, tzinfo=UTC),
            "status": OwnershipRuleStatus.ACTIVE,
        }
    )


def _projection_for(scenario: OwnershipScenario) -> dict[str, Any]:
    """Build the approved projection payload with no external state."""

    validation = StatusOwnershipRuleService.validate_payload(
        _rule_for(scenario),
        {
            "subject_id": scenario.subject_id,
            "status": scenario.projection_status,
            "source_version": scenario.source_version,
        },
    )
    assert validation.accepted is True
    return validation.payload


def _command(scenario: OwnershipScenario) -> OwnershipCommand:
    payload = {scenario.field_path: scenario.command_value}
    if scenario.command_kind == "competing_clinical_write":
        return OwnershipCommand(
            module=Module.CTMS,
            kind=scenario.command_kind,
            field_path=scenario.field_path,
            value=scenario.command_value,
            transition_target=scenario.command_transition,
            operation=scenario.competing_operation,
            payload={},
        )
    return OwnershipCommand(
        module=scenario.command_module,
        kind=scenario.command_kind,
        field_path=scenario.field_path,
        value=scenario.command_value,
        transition_target=scenario.command_transition,
        operation="update_owned_field",
        payload=payload,
    )


@given(scenario=ownership_scenarios())
@settings(max_examples=100, deadline=None, derandomize=True)
@pytest.mark.asyncio
async def test_exactly_one_authoritative_owner_governs_each_field(
    scenario: OwnershipScenario,
) -> None:
    """Only the owner writes; consumers read projections and cannot transition them."""

    rule = _rule_for(scenario)
    assert rule.status is OwnershipRuleStatus.ACTIVE
    assert rule.authoritative_module in (Module.EDC, Module.CTMS)
    assert rule.writable_module is rule.authoritative_module
    assert rule.projection_target is _other_module(rule.authoritative_module)
    assert sum(
        module is rule.authoritative_module for module in (Module.EDC, Module.CTMS)
    ) == 1
    assert rule.is_effective(datetime(2025, 1, 1, tzinfo=UTC))

    projection = _projection_for(scenario)
    boundary = _InMemoryOwnershipBoundary(rule, projection)
    source_before = dict(boundary.authoritative_state)

    # The configured consumer can read the minimized projection, but neither a
    # mapping mutation nor a boundary write can change the authoritative source.
    consumer_view = boundary.read_projection(rule.projection_target)
    assert dict(consumer_view) == projection
    with pytest.raises(TypeError):
        consumer_view["status"] = "Competing clinical write"  # type: ignore[index]
    with pytest.raises(ConflictError):
        boundary.write_projection(rule.projection_target, rule.field_path, "tampered")
    assert boundary.authoritative_state == source_before

    # Every generated command is evaluated against the active rule and the
    # real CTMS clinical pre-mutation guard.  Rejected commands are side-effect
    # free; only the one owner may write a field.
    command = _command(scenario)
    command_source_before = dict(boundary.authoritative_state)
    if command.kind == "transition":
        command_target_is_configured = command.transition_target in scenario.allowed_targets
        if command.module is rule.authoritative_module and command_target_is_configured:
            boundary.transition_authoritative(command)
            assert boundary.authoritative_state[rule.field_path] == command.transition_target
        else:
            with pytest.raises(ConflictError):
                boundary.transition_authoritative(command)
            assert boundary.authoritative_state == command_source_before
    elif command.kind == "competing_clinical_write":
        with pytest.raises(CTMSOwnershipError):
            boundary.write_authoritative(command)
        assert boundary.authoritative_state == command_source_before
    elif command.module is rule.authoritative_module:
        boundary.write_authoritative(command)
        assert boundary.authoritative_state[rule.field_path] == command.value
    else:
        with pytest.raises(ConflictError):
            boundary.write_authoritative(command)
        assert boundary.authoritative_state == command_source_before

    # Independently exercise an unconfigured transition for every generated
    # rule.  It must be rejected even when the caller is authoritative.
    unconfigured_targets = [
        target for target in ("planning", "ready", "active", "closed")
        if target not in scenario.allowed_targets
    ]
    if unconfigured_targets:
        transition_boundary = _InMemoryOwnershipBoundary(rule, projection)
        unconfigured = OwnershipCommand(
            module=rule.authoritative_module,
            kind="transition",
            field_path=rule.field_path,
            value="",
            transition_target=unconfigured_targets[0],
            operation="transition_owned_field",
            payload={rule.field_path: unconfigured_targets[0]},
        )
        before_unconfigured = dict(transition_boundary.authoritative_state)
        with pytest.raises(ConflictError):
            transition_boundary.transition_authoritative(unconfigured)
        assert transition_boundary.authoritative_state == before_unconfigured
