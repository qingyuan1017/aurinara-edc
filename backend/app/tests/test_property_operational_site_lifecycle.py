"""Property test for the CTMS operational site lifecycle.

**Validates: Requirements 4.1-4.11, 14.5-14.6**

Property 5: Operational site lifecycle is independent of clinical site use.

The test drives the real ``OperationalSiteService`` with deterministic in-memory
session and bookkeeping fakes.  No database, network, worker, or external service
is used.  The canonical EDC Site is held separately so every accepted CTMS
operation can be checked for clinical-state preservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.operational_site import (
    ActivationAction,
    ActivationActionStatus,
    OperationalSite,
    OperationalSiteStatus,
    RetentionState,
)
from app.models.ctms.work import OperationalContact, OperationalContactStatus
from app.models.site import Site, SiteStatus
from app.services.operational_site_service import OperationalSiteService
from app.services.operational_site_service import _SITE_TRANSITIONS
from app.services.ctms_ownership_guard import CTMSOwnershipError


@dataclass(frozen=True)
class ActionInput:
    """Generated operational action data."""

    action_type: str
    responsible_role: str
    planned_date: date
    complete: bool
    evidence: str


@dataclass(frozen=True)
class ContactInput:
    """Generated linked operational contact data."""

    name: str
    role: str


class _ScalarResult:
    def __init__(self, values: list[Any]):
        self._values = values

    def scalars(self) -> _ScalarResult:
        return self

    def first(self) -> Any | None:
        return self._values[0] if self._values else None

    def all(self) -> list[Any]:
        return list(self._values)


class InMemorySession:
    """Small async-session fake that evaluates the service's select predicates."""

    def __init__(self, canonical_site: Site):
        self.records: list[Any] = [canonical_site]
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        if isinstance(value, OperationalSite):
            value.created_at = value.created_at or datetime.now(UTC)
            value.updated_at = value.updated_at or value.created_at
        elif isinstance(value, ActivationAction):
            value.created_at = value.created_at or datetime.now(UTC)
            value.updated_at = value.updated_at or value.created_at
        self.records.append(value)

    async def flush(self) -> None:
        return None

    async def execute(self, statement: Any) -> _ScalarResult:
        entity = statement.column_descriptions[0]["entity"]
        values = [record for record in self.records if isinstance(record, entity)]
        for predicate in statement._where_criteria:
            values = [value for value in values if self._matches(value, predicate)]
        if statement._order_by_clauses:
            order_column = next(iter(statement._order_by_clauses))
            key = getattr(order_column, "key", None)
            if key is None:
                key = getattr(getattr(order_column, "element", None), "key", None)
            if key is None:
                raise AssertionError(f"Unsupported in-memory ordering: {order_column!r}")
            values.sort(key=lambda value: getattr(value, key))
        return _ScalarResult(values)

    @staticmethod
    def _matches(value: Any, predicate: Any) -> bool:
        key = getattr(predicate.left, "key", None)
        actual = getattr(value, key)
        operation_name = getattr(predicate.operator, "__name__", "")
        expected = getattr(predicate.right, "value", None)
        if operation_name in {"eq", "is_"}:
            return actual == expected
        if operation_name in {"ne", "is_not"}:
            return actual != expected
        if operation_name in {"in_op", "not_in_op"}:
            contained = actual in (expected or ())
            return contained if operation_name == "in_op" else not contained
        raise AssertionError(f"Unsupported in-memory predicate: {predicate!r}")

    def snapshot(self) -> tuple[tuple[str, str, str, str | None, str | None], ...]:
        """Return CTMS state without timestamps that naturally vary per operation."""

        result = []
        for record in self.records:
            if isinstance(record, OperationalSite):
                result.append(
                    (
                        "profile",
                        str(record.id),
                        record.status,
                        record.responsible_role,
                        record.retention_state,
                    )
                )
            elif isinstance(record, ActivationAction):
                result.append(
                    (
                        "action",
                        str(record.id),
                        record.status,
                        record.responsible_role,
                        record.evidence_reference,
                    )
                )
            elif isinstance(record, OperationalContact):
                result.append(
                    ("contact", str(record.id), record.status, record.role, record.retention_state)
                )
        return tuple(result)


def _site_snapshot(site: Site) -> tuple[Any, ...]:
    """Capture canonical EDC fields that CTMS must never change."""

    return (
        site.id,
        site.study_id,
        site.site_number,
        site.name,
        site.principal_investigator,
        site.country,
        site.region,
        site.address,
        site.status,
        site.deleted_at,
    )


def _timestamp(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _make_scenario() -> st.SearchStrategy[dict[str, Any]]:
    safe_role = st.sampled_from(("CRA", "Regulatory Lead", "Site Manager", "Data Manager"))
    safe_date = st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31))
    evidence = st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=1,
        max_size=20,
    ).map(lambda value: f"evidence://{value}")
    action = st.builds(
        ActionInput,
        action_type=st.sampled_from(
            ("Regulatory Approval", "Site Contract", "Training", "Equipment", "Budget Review")
        ),
        responsible_role=safe_role,
        planned_date=safe_date,
        complete=st.booleans(),
        evidence=evidence,
    )
    contact = st.builds(
        ContactInput,
        name=st.sampled_from(("Primary Contact", "Backup Contact", "Regulatory Contact")),
        role=safe_role,
    )
    return st.fixed_dictionaries(
        {
            "profile_role": safe_role,
            "profile_date": safe_date,
            "monitoring_readiness": st.sampled_from(("Not Ready", "In Review", "Ready")),
            "status_targets": st.lists(
                st.sampled_from(list(OperationalSiteStatus)[:-1]), min_size=1, max_size=12
            ),
            "actions": st.lists(action, min_size=1, max_size=5, unique_by=lambda item: item.action_type),
            "contacts": st.lists(contact, min_size=1, max_size=3),
            "edc_field": st.sampled_from(
                (
                    "clinical_data",
                    "study_version_id",
                    "visit_instance_status",
                    "query_message",
                    "field_values",
                )
            ),
            "archive_reason": st.sampled_from(
                ("EDC site archived", "Site record retired", "Canonical site closed")
            ),
        }
    )


def _add_contact(session: InMemorySession, site: Site, actor_id: UUID, contact: ContactInput) -> None:
    session.add(
        OperationalContact(
            id=uuid4(),
            study_id=site.study_id,
            site_id=site.id,
            name=contact.name,
            role=contact.role,
            organization="Generated organization",
            channels={},
            status=OperationalContactStatus.ACTIVE.value,
            retention_state=RetentionState.ACTIVE.value,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )


async def _record_mutation(_session: Any, **kwargs: Any) -> None:
    """Async side effect target replaced per example by the test."""


@settings(max_examples=100, deadline=None)
@given(scenario=_make_scenario())
@pytest.mark.asyncio
async def test_operational_site_lifecycle_is_independent_of_canonical_edc_site(scenario: dict[str, Any]):
    """Generated site workflows retain CTMS history and never mutate EDC state.

    **Validates: Requirements 4.1-4.11, 14.5-14.6**
    """

    actor_id = uuid4()
    study_id = uuid4()
    site = Site(
        id=uuid4(),
        study_id=study_id,
        site_number="GENERATED-001",
        name="Canonical EDC Site",
        principal_investigator="Dr. Canonical",
        country="US",
        region="West",
        address="Canonical address",
        status=SiteStatus.active,
    )
    canonical_before = _site_snapshot(site)
    session = InMemorySession(site)
    service = OperationalSiteService()
    mutations: list[dict[str, Any]] = []

    async def record_mutation(_session: Any, **kwargs: Any) -> None:
        mutations.append(kwargs)

    with (
        patch(
            "app.services.operational_site_service.ctms_atomicity_service.record_mutation",
            new=AsyncMock(side_effect=record_mutation),
        ),
        patch(
            "app.services.operational_site_service.audit_service.record",
            new=AsyncMock(),
        ),
    ):
        profile = await service.create_profile(
            session,
            site_id=site.id,
            actor_id=actor_id,
            payload={
                "monitoring_readiness": scenario["monitoring_readiness"],
                "responsible_role": scenario["profile_role"],
                "planned_activation_date": _timestamp(scenario["profile_date"]),
            },
            correlation_id="generated-site-profile",
        )
        assert profile.site_id == site.id
        assert profile.study_id == study_id
        assert profile.responsible_role == scenario["profile_role"]
        assert profile.planned_activation_date == _timestamp(scenario["profile_date"])

        for index, target in enumerate(scenario["status_targets"]):
            current = profile.status
            if target == current:
                await service.transition_status(session, profile, target, actor_id=actor_id)
                continue
            allowed = target.value in _SITE_TRANSITIONS[current]
            if not allowed:
                with pytest.raises(ConflictError):
                    await service.transition_status(
                        session, profile, target, reason=f"attempt-{index}", actor_id=actor_id
                    )
                assert profile.status == current
                continue

            with pytest.raises(ValidationError):
                await service.transition_status(session, profile, target, actor_id=actor_id)
            assert profile.status == current
            await service.transition_status(
                session,
                profile,
                target,
                reason=f"status transition {index}",
                actor_id=actor_id,
                correlation_id=f"status-{index}",
            )
            assert profile.status == target.value

        created_actions: list[tuple[ActivationAction, ActionInput]] = []
        for index, action_input in enumerate(scenario["actions"]):
            action = await service.create_activation_action(
                session,
                site_id=site.id,
                actor_id=actor_id,
                payload={
                    "action_type": action_input.action_type,
                    "responsible_role": action_input.responsible_role,
                    "planned_date": _timestamp(action_input.planned_date),
                },
                correlation_id=f"action-{index}",
            )
            duplicate = await service.create_activation_action(
                session,
                site_id=site.id,
                actor_id=actor_id,
                payload={"action_type": action_input.action_type},
                correlation_id=f"duplicate-{index}",
            )
            assert duplicate.id == action.id
            assert duplicate is action
            assert action.responsible_role == action_input.responsible_role
            assert action.planned_date == _timestamp(action_input.planned_date)
            created_actions.append((action, action_input))

            if action_input.complete:
                await service.transition_activation_action(
                    session,
                    action,
                    ActivationActionStatus.IN_PROGRESS,
                    reason="Activation work started",
                    actor_id=actor_id,
                    correlation_id=f"action-start-{index}",
                )
                completed = await service.complete_activation_action(
                    session,
                    action,
                    action_input.evidence,
                    actor_id=actor_id,
                    reason="Completion evidence verified",
                    correlation_id=f"action-complete-{index}",
                )
                assert completed.status == ActivationActionStatus.COMPLETED.value
                assert completed.completed_by == actor_id
                assert completed.completed_at is not None
                assert completed.completed_at.tzinfo is not None
                assert completed.evidence_reference == action_input.evidence
            else:
                cancelled = await service.transition_activation_action(
                    session,
                    action,
                    ActivationActionStatus.CANCELLED,
                    reason="Activation action cancelled",
                    actor_id=actor_id,
                    correlation_id=f"action-cancel-{index}",
                )
                assert cancelled.status == ActivationActionStatus.CANCELLED.value

        for contact in scenario["contacts"]:
            _add_contact(session, site, actor_id, contact)

        ctms_before_edc_attempt = session.snapshot()
        for field in (scenario["edc_field"],):
            with pytest.raises(CTMSOwnershipError):
                await service.update_profile(
                    session,
                    profile,
                    {field: "attempted clinical mutation"},
                    actor_id=actor_id,
                )
            assert session.snapshot() == ctms_before_edc_attempt
            assert _site_snapshot(site) == canonical_before

        await service.on_edc_site_archived(
            session,
            site_id=site.id,
            actor_id=actor_id,
            reason=scenario["archive_reason"],
            correlation_id="edc-archive-event",
        )

    assert profile.status == OperationalSiteStatus.SITE_ARCHIVED.value
    assert profile.retention_state == RetentionState.ARCHIVED.value
    assert profile.archived_by == actor_id
    assert profile.retention_reason == scenario["archive_reason"]
    assert all(
        action.status == ActivationActionStatus.ARCHIVED.value
        and action.retention_state == RetentionState.ARCHIVED.value
        and action.archived_by == actor_id
        for action, _ in created_actions
    )
    linked_contacts = [
        record for record in session.records if isinstance(record, OperationalContact)
    ]
    assert linked_contacts
    assert all(
        contact.status == OperationalContactStatus.ARCHIVED.value
        and contact.retention_state == RetentionState.ARCHIVED.value
        and contact.archived_by == actor_id
        for contact in linked_contacts
    )
    assert _site_snapshot(site) == canonical_before

    # Every accepted status/action/archive mutation is routed through the CTMS
    # bookkeeping hook, preserving reason/history/correlation in one transaction.
    assert mutations
    assert all(mutation["site_id"] == site.id for mutation in mutations)
    assert any(mutation["action"] == "archive" for mutation in mutations)
    assert any(
        mutation["action"] == "status_transition"
        and mutation["reason"]
        for mutation in mutations
    )
    assert any(
        mutation["action"] == "complete"
        and mutation["reason"] == "Completion evidence verified"
        for mutation in mutations
    ) == any(action_input.complete for _, action_input in created_actions)
