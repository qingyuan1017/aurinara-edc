"""Property-based verification of minimized CTMS projection payloads.

# Feature: ctms-integration, Property 10: Projection payloads obey versioned minimization allowlists

**Validates: Requirements 1.6, 5.12-5.13, 8.1-8.9, 8.11-8.12, 12.11-12.12**

The property uses the task 4.1 typed ownership rules and task 4.2 projection
service with deterministic in-memory persistence.  It does not call a database,
worker, network, or external service.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ctms import Module
from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType
from app.models.ctms.projection import ProjectionStatus
from app.schemas.ctms.ownership import ProjectionFieldType
from app.services.ctms_ownership_guard import CTMSOwnershipError, assert_ctms_command_safe
from app.services.ctms_projection_service import CTMSProjectionService
from app.services.status_ownership_rule_service import (
    CompiledOwnershipRule,
    StatusOwnershipRuleService,
)


@dataclass(frozen=True)
class SourceRecord:
    """Canonical source metadata and the source payload being projected."""

    source_record_id: UUID
    source_module: Module
    study_id: UUID
    site_id: UUID
    source_version: int
    source_timestamp: datetime


@dataclass(frozen=True)
class ProjectionScenario:
    """One versioned rule, source record, approved payload, and hostile payload."""

    projection_type: ProjectionType
    rule: CompiledOwnershipRule
    source: SourceRecord
    approved_payload: dict[str, Any]
    rejected_payload: dict[str, Any]
    prohibited_key: str
    arbitrary_nested_payload: Any


class _Session:
    """Minimal deterministic session used by the in-memory repository."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


class _ProjectionRepository:
    """In-memory projection repository with the production repository contract."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, UUID], Any] = {}

    async def get(self, session: _Session, *, projection_type: str, source_module: str, source_record_id: UUID) -> Any:
        return self.rows.get((projection_type, source_module, source_record_id))

    async def add(self, session: _Session, projection: Any) -> Any:
        session.add(projection)
        await session.flush()
        self.rows[(projection.projection_type, projection.source_module, projection.source_record_id)] = projection
        return projection


def _json_values() -> st.SearchStrategy[Any]:
    """Generate bounded arbitrary nested JSON-like values for hostile fields."""

    leaves = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(max_size=20),
    )
    return st.recursive(
        leaves,
        lambda children: st.one_of(
            st.lists(children, max_size=3),
            st.dictionaries(st.text(max_size=12), children, max_size=3),
        ),
        max_leaves=10,
    )


def _field_type(declaration: Any) -> str:
    return str(declaration.get("type")) if isinstance(declaration, dict) else str(declaration)


def _value_for(draw: st.DrawFn, declaration: Any) -> Any:
    """Generate a value of the exact type declared by an active allowlist."""

    field_type = _field_type(declaration)
    if field_type == ProjectionFieldType.UUID.value:
        return draw(st.uuids(version=4))
    if field_type == ProjectionFieldType.STRING.value:
        return draw(st.text(max_size=24))
    if field_type == ProjectionFieldType.INTEGER.value:
        return draw(st.integers(min_value=-1000, max_value=1000))
    if field_type == ProjectionFieldType.NUMBER.value:
        return draw(st.floats(allow_nan=False, allow_infinity=False, width=32))
    if field_type == ProjectionFieldType.BOOLEAN.value:
        return draw(st.booleans())
    if field_type == ProjectionFieldType.DATETIME.value:
        return draw(
            st.datetimes(
                min_value=datetime(2020, 1, 1),
                max_value=datetime(2030, 1, 1),
                timezones=st.just(UTC),
            )
        )
    if field_type == ProjectionFieldType.ENUM.value:
        choices = declaration.get("values", ()) if isinstance(declaration, dict) else ()
        return draw(st.sampled_from(tuple(choices)))
    raise AssertionError(f"unsupported generated declaration: {field_type}")


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    cursor = payload
    parts = path.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _expected_value(value: Any, declaration: Any) -> Any:
    """Mirror only documented scalar normalization for an independent assertion."""

    field_type = _field_type(declaration)
    if field_type == ProjectionFieldType.UUID.value:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    if field_type == ProjectionFieldType.DATETIME.value:
        return value.astimezone(UTC).isoformat()
    return value


def _flatten_paths(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            flattened.update(_flatten_paths(child, path))
        else:
            flattened[path] = child
    return flattened


def _expected_rejection_reason(payload: Mapping[str, Any]) -> str:
    """Use the ownership guard's contract for EDC-owned hostile fields."""

    try:
        assert_ctms_command_safe(payload, operation="project_projection")
    except CTMSOwnershipError as error:
        return str(error.details["reason"])
    return "PROJECTION_FIELD_NOT_ALLOWED"


@st.composite
def projection_scenarios(draw: st.DrawFn) -> ProjectionScenario:
    """Generate every projection contract plus nested approved and prohibited data."""

    projection_type = draw(st.sampled_from(tuple(ProjectionType)))
    typed_allowlist = StatusOwnershipRuleService.default_allowlist(projection_type)
    # A dotted allowlist entry forces the validator to handle nested source
    # payloads while still producing a typed, minimized read model.
    typed_allowlist["metadata.source_label"] = ProjectionFieldType.STRING.value
    rule = StatusOwnershipRuleService.compile_rule(
        {
            "entity_type": "ProjectionSource",
            "field_path": "status",
            "authoritative_module": Module.EDC,
            "writable_module": Module.EDC,
            "projection_target": Module.CTMS,
            "projection_type": projection_type,
            "allowed_transitions": {},
            "typed_allowlist": typed_allowlist,
            "version": draw(st.integers(min_value=1, max_value=50)),
            "effective_from": datetime(2020, 1, 1, tzinfo=UTC),
            "status": OwnershipRuleStatus.ACTIVE,
        }
    )

    approved_payload: dict[str, Any] = {}
    for path, declaration in rule.typed_allowlist.items():
        _set_path(approved_payload, path, _value_for(draw, declaration))

    arbitrary_nested_payload = draw(_json_values())
    prohibited_key = draw(
        st.sampled_from(
            (
                "clinical_data",
                "field_values",
                "source_documents",
                "credentials",
                "password",
                "unrestricted_query_messages",
                "query_message",
                "raw_event_body",
                "clinical_audit_history",
                "subject_number",
                "patient_identifier",
                "direct_identifier",
                "clinical_identifier",
                "patient_id",
                "mrn",
            )
        )
    )
    rejected_payload = dict(approved_payload)
    rejected_payload[prohibited_key] = {
        "nested": arbitrary_nested_payload,
        "credential_value": draw(st.text(min_size=1, max_size=32)),
    }

    return ProjectionScenario(
        projection_type=projection_type,
        rule=rule,
        source=SourceRecord(
            source_record_id=draw(st.uuids(version=4)),
            source_module=draw(st.sampled_from((Module.EDC, Module.CTMS))),
            study_id=draw(st.uuids(version=4)),
            site_id=draw(st.uuids(version=4)),
            source_version=draw(st.integers(min_value=1, max_value=1000)),
            source_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        approved_payload=approved_payload,
        rejected_payload=rejected_payload,
        prohibited_key=prohibited_key,
        arbitrary_nested_payload=arbitrary_nested_payload,
    )


@given(scenario=projection_scenarios())
@settings(max_examples=100, deadline=None, derandomize=True)
@pytest.mark.asyncio
async def test_projection_payloads_obey_versioned_minimization_allowlists(
    scenario: ProjectionScenario,
) -> None:
    """Allowlisted typed fields survive; prohibited records retain only fingerprints."""

    assert scenario.rule.status is OwnershipRuleStatus.ACTIVE
    assert scenario.rule.is_effective(datetime(2025, 1, 1, tzinfo=UTC))
    assert scenario.rule.version >= 1
    assert scenario.rule.projection_type is scenario.projection_type

    repository = _ProjectionRepository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()
    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        accepted = await service.apply_projection(
            session,
            rule=scenario.rule,
            source_module=scenario.source.source_module,
            source_record_id=scenario.source.source_record_id,
            payload=scenario.approved_payload,
            source_version=scenario.source.source_version,
            source_timestamp=scenario.source.source_timestamp,
            correlation_id="property-10-accepted",
            study_id=scenario.source.study_id,
            site_id=scenario.source.site_id,
        )

        rejected_source_id = uuid4()
        rejected = await service.apply_projection(
            session,
            rule=scenario.rule,
            source_module=scenario.source.source_module,
            source_record_id=rejected_source_id,
            payload=scenario.rejected_payload,
            source_version=scenario.source.source_version,
            source_timestamp=scenario.source.source_timestamp,
            correlation_id="property-10-rejected",
            study_id=scenario.source.study_id,
            site_id=scenario.source.site_id,
        )

    # The accepted record contains every approved typed path and nothing else;
    # UUIDs and timestamps are normalized to their serialized representations.
    expected_flattened = {
        path: _expected_value(value, scenario.rule.typed_allowlist[path])
        for path, value in _flatten_paths(scenario.approved_payload).items()
    }
    actual_flattened = _flatten_paths(accepted.projection.payload_json)
    assert accepted.applied is True
    assert accepted.projection.status is ProjectionStatus.CURRENT
    assert set(actual_flattened) == set(scenario.rule.typed_allowlist)
    assert actual_flattened == expected_flattened
    assert accepted.projection.rule_version == scenario.rule.version
    assert accepted.projection.payload_fingerprint == StatusOwnershipRuleService.fingerprint(
        accepted.projection.payload_json
    )

    # A hostile nested source payload is rejected before persistence.  The
    # retained row has no payload values or raw source body, only a stable hash
    # of field names and a sanitized reason.
    assert rejected.rejected is True
    assert rejected.applied is False
    assert rejected.projection.status is ProjectionStatus.REJECTED
    assert rejected.projection.payload_json == {}
    # Clinical-owned hostile fields are rejected by the pre-mutation ownership
    # guard; other prohibited/unknown fields are rejected by the versioned
    # projection allowlist. Both paths retain only sanitized metadata.
    expected_rejection_reason = _expected_rejection_reason(scenario.rejected_payload)
    assert rejected.projection.rejection_reason == expected_rejection_reason
    assert rejected.projection.rejected_fields_fingerprint == service.field_fingerprint(
        tuple(sorted(scenario.rejected_payload))
    )
    retained = json.dumps(
        {
            "payload": rejected.projection.payload_json,
            "rejected_fields_fingerprint": rejected.projection.rejected_fields_fingerprint,
            "reason": rejected.projection.rejection_reason,
        },
        sort_keys=True,
    )
    assert set(json.loads(retained)) == {
        "payload",
        "rejected_fields_fingerprint",
        "reason",
    }
    assert scenario.prohibited_key not in retained
