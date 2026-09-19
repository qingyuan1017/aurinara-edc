"""Property test for CTMS monitoring/protocol visit separation.

**Validates: Requirements 6.1-6.2, 6.6-6.15, 14.7**

Property 8: Monitoring activities remain separate from protocol visits.

The property drives the real ``MonitoringService`` with deterministic in-memory
session, EDC state, and atomicity fakes.  It does not use a database, worker,
network, or external service.  Monitoring records may reference an EDC
``VisitInstance``, but scheduling and lifecycle changes must never mutate the
EDC visit, its protocol definition, forms, clinical values, or freeze/lock
records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlan,
    MonitoringPlanVersion,
)
from app.models.identity import User, UserStatus
from app.models.lock import FreezeLock, FreezeLockObjectType, FreezeLockType
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitInstance, VisitInstanceStatus
from app.services.monitoring_service import MonitoringService


@dataclass(frozen=True)
class ProtocolDefinition:
    """EDC-owned protocol definition held outside CTMS persistence."""

    id: UUID
    name: str
    target_day: int
    window_before: int
    window_after: int


@dataclass(frozen=True)
class EDCState:
    """The clinical records that a monitoring command is forbidden to change."""

    visit: VisitInstance
    definition: ProtocolDefinition
    forms: tuple[tuple[str, str], ...]
    clinical_data: tuple[tuple[str, str], ...]
    locks: tuple[tuple[str, str, bool], ...]

    def snapshot(self) -> tuple[Any, ...]:
        return (
            (
                self.visit.id,
                self.visit.subject_id,
                self.visit.visit_definition_id,
                self.visit.name,
                self.visit.visit_date,
                self.visit.window_status,
                self.visit.status,
            ),
            (
                self.definition.id,
                self.definition.name,
                self.definition.target_day,
                self.definition.window_before,
                self.definition.window_after,
            ),
            self.forms,
            self.clinical_data,
            self.locks,
        )


class _ScalarResult:
    """Minimal scalar result returned by the deterministic session fake."""

    def __init__(self, values: list[Any]):
        self._values = values

    def scalars(self) -> _ScalarResult:
        return self

    def first(self) -> Any | None:
        return self._values[0] if self._values else None

    def all(self) -> list[Any]:
        return list(self._values)


class InMemorySession:
    """Async session fake that evaluates the service's SQLAlchemy predicates."""

    def __init__(self, records: list[Any]):
        self.records = list(records)
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        now = datetime.now(UTC)
        if hasattr(value, "created_at") and getattr(value, "created_at", None) is None:
            value.created_at = now
        if hasattr(value, "updated_at") and getattr(value, "updated_at", None) is None:
            value.updated_at = now
        self.added.append(value)
        self.records.append(value)

    async def flush(self) -> None:
        return None

    async def execute(self, statement: Any) -> _ScalarResult:
        entity = statement.column_descriptions[0]["entity"]
        values = [record for record in self.records if isinstance(record, entity)]
        for predicate in statement._where_criteria:
            values = [record for record in values if self._matches(record, predicate)]
        if statement._order_by_clauses:
            order_column = next(iter(statement._order_by_clauses))
            key = getattr(order_column, "key", None)
            if key is None:
                key = getattr(getattr(order_column, "element", None), "key", None)
            values.sort(key=lambda record: getattr(record, key))
        return _ScalarResult(values)

    def ctms_snapshot(self) -> tuple[Any, ...]:
        """Capture CTMS state while excluding naturally changing timestamps."""

        plans = []
        versions = []
        activities = []
        for record in self.records:
            if isinstance(record, MonitoringPlan):
                plans.append((record.id, record.study_id, record.site_id, record.name, record.status, record.current_version_id))
            elif isinstance(record, MonitoringPlanVersion):
                versions.append((record.id, record.plan_id, record.version_number, record.status, record.activity_types, record.amendment_reason))
            elif isinstance(record, MonitoringActivity):
                activities.append((record.id, record.plan_version_id, record.activity_type, record.planned_date, record.assigned_cra_id, record.status, record.edc_visit_instance_id, record.completion_evidence, record.completion_notes, record.cancellation_reason))
        return (tuple(plans), tuple(versions), tuple(activities))

    def _matches(self, record: Any, predicate: Any) -> bool:
        key = getattr(predicate.left, "key", None)
        actual = getattr(record, key, None)
        if actual is None and isinstance(record, VisitInstance):
            subject = getattr(record, "subject", None)
            if subject is None:
                subject_id = getattr(record, "subject_id", None)
                subject = next(
                    (candidate for candidate in self.records if isinstance(candidate, Subject) and candidate.id == subject_id),
                    None,
                )
            actual = getattr(subject, key, None) if subject is not None else None
        operation_name = getattr(predicate.operator, "__name__", "")
        expected = getattr(predicate.right, "value", None)
        if operation_name in {"eq", "is_"}:
            return actual == expected
        if operation_name in {"ne", "is_not"}:
            return actual != expected
        raise AssertionError(f"Unsupported in-memory predicate: {predicate!r}")


def _make_scenario() -> st.SearchStrategy[dict[str, Any]]:
    operation = st.sampled_from(("reschedule", "complete", "cancel"))
    mutation_field = st.sampled_from(
        (
            "clinical_data",
            "visit_date",
            "window_status",
            "form_instance",
            "field_values",
            "lock_status",
            "electronic_signature",
        )
    )
    return st.fixed_dictionaries(
        {
            "reference_mode": st.sampled_from(("stable", "display_name", "unknown", "wrong_scope")),
            "protocol_state": st.sampled_from(("open", "Frozen", "Locked")),
            "operations": st.lists(operation, min_size=1, max_size=4),
            "mutation_field": mutation_field,
            "inject_clinical_mutation": st.booleans(),
            "activity_type": st.sampled_from([item.value for item in MonitoringActivityType]),
            "day_offset": st.integers(min_value=1, max_value=365),
        }
    )


def _make_user() -> User:
    return User(
        id=uuid4(),
        email=f"monitoring-{uuid4().hex}@test.local",
        first_name="Generated",
        last_name="CRA",
        status=UserStatus.active,
    )


def _make_scope(actor: User, suffix: str) -> tuple[Study, Site, Subject, VisitInstance, EDCState]:
    study = Study(
        id=uuid4(),
        study_code=f"MON-{suffix}-{uuid4().hex[:8]}",
        title="Canonical EDC study",
        status=StudyStatus.active,
        created_by=actor.id,
    )
    site = Site(
        id=uuid4(),
        study_id=study.id,
        site_number=f"{uuid4().int % 100000:05d}",
        name="Canonical EDC site",
        status=SiteStatus.active,
    )
    subject = Subject(
        id=uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=uuid4(),
        subject_number=f"SUBJ-{uuid4().hex[:8]}",
        status=SubjectStatus.enrolled,
        created_by=actor.id,
    )
    visit = VisitInstance(
        id=uuid4(),
        subject_id=subject.id,
        visit_definition_id=uuid4(),
        name="Baseline Visit",
        visit_date=date(2026, 1, 15),
        window_status="in_window",
        status=VisitInstanceStatus.scheduled,
    )
    definition = ProtocolDefinition(
        id=visit.visit_definition_id,
        name=visit.name,
        target_day=1,
        window_before=2,
        window_after=3,
    )
    locks = ()
    edc_state = EDCState(
        visit=visit,
        definition=definition,
        forms=(("form-instance-1", "submitted"),),
        clinical_data=(("field-1", "unchanged clinical value"),),
        locks=locks,
    )
    return study, site, subject, visit, edc_state


def _add_protocol_lock(
    session: InMemorySession, visit: VisitInstance, actor: User, state: str
) -> EDCState:
    if state == "open":
        return EDCState(
            visit=visit,
            definition=ProtocolDefinition(visit.visit_definition_id, visit.name, 1, 2, 3),
            forms=(("form-instance-1", "submitted"),),
            clinical_data=(("field-1", "unchanged clinical value"),),
            locks=(),
        )
    lock_type = FreezeLockType.freeze.value if state == "Frozen" else FreezeLockType.lock.value
    lock = FreezeLock(
        id=uuid4(),
        object_type=FreezeLockObjectType.visit.value,
        object_id=visit.id,
        lock_type=lock_type,
        is_active=True,
        locked_by=actor.id,
        locked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(lock)
    return EDCState(
        visit=visit,
        definition=ProtocolDefinition(visit.visit_definition_id, visit.name, 1, 2, 3),
        forms=(("form-instance-1", "submitted"),),
        clinical_data=(("field-1", "unchanged clinical value"),),
        locks=((lock.object_type, lock.lock_type, lock.is_active),),
    )


def _reference_for(scenario: dict[str, Any], visit: VisitInstance, other_visit: VisitInstance) -> UUID | str:
    return {
        "stable": visit.id,
        "display_name": visit.name,
        "unknown": uuid4(),
        "wrong_scope": other_visit.id,
    }[scenario["reference_mode"]]


def _apply_operation_data(operation: str, day_offset: int) -> tuple[datetime, str, dict[str, str]]:
    planned = datetime(2026, 1, 15, 10, 0, tzinfo=UTC) + timedelta(days=day_offset)
    if operation == "reschedule":
        return planned, "Generated rescheduling reason", {}
    if operation == "complete":
        return planned, "Generated completion evidence", {"reference": "evidence://generated"}
    return planned, "Generated cancellation reason", {}


@settings(max_examples=100, deadline=None)
@given(scenario=_make_scenario())
@pytest.mark.asyncio
async def test_monitoring_activities_remain_separate_from_protocol_visits(
    scenario: dict[str, Any],
):
    """Monitoring workflows preserve all generated EDC clinical state.

    **Validates: Requirements 6.1-6.2, 6.6-6.15, 14.7**
    """

    actor = _make_user()
    study, site, subject, visit, edc_state = _make_scope(actor, "PRIMARY")
    other_study, other_site, other_subject, other_visit, other_edc = _make_scope(actor, "OTHER")
    records = [actor, study, site, subject, visit, other_study, other_site, other_subject, other_visit]
    session = InMemorySession(records)
    edc_state = _add_protocol_lock(session, visit, actor, scenario["protocol_state"])
    other_edc_state = other_edc
    service = MonitoringService()
    mutations: list[dict[str, Any]] = []

    async def record_mutation(_session: Any, **kwargs: Any) -> None:
        mutations.append(kwargs)

    with patch(
        "app.services.monitoring_service.ctms_atomicity_service.record_mutation",
        new=AsyncMock(side_effect=record_mutation),
    ):
        plan = await service.create_plan(
            session,
            study_id=study.id,
            site_id=site.id,
            actor_id=actor.id,
            correlation_id="property-plan",
            payload={
                "name": "Generated monitoring plan",
                "activity_types": [scenario["activity_type"]],
            },
        )
        await service.publish_plan(session, plan, actor_id=actor.id, correlation_id="property-publish")

        edc_before = (edc_state.snapshot(), other_edc_state.snapshot())
        ctms_before_command = session.ctms_snapshot()
        reference = _reference_for(scenario, visit, other_visit)
        payload: dict[str, Any] = {
            "activity_type": scenario["activity_type"],
            "planned_date": datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            "assigned_cra_id": actor.id,
            "edc_visit_instance_id": reference,
        }
        if scenario["inject_clinical_mutation"]:
            payload[scenario["mutation_field"]] = {"attempt": "must be rejected"}

        invalid_reference = scenario["reference_mode"] != "stable"
        invalid_payload = scenario["inject_clinical_mutation"]
        if invalid_reference or invalid_payload:
            with pytest.raises((ConflictError, NotFoundError, ValidationError)):
                await service.schedule_activity(
                    session,
                    plan=plan,
                    actor_id=actor.id,
                    correlation_id="property-rejected-command",
                    payload=payload,
                )
            assert session.ctms_snapshot() == ctms_before_command
            assert (edc_state.snapshot(), other_edc_state.snapshot()) == edc_before
            return

        activity = await service.schedule_activity(
            session,
            plan=plan,
            actor_id=actor.id,
            correlation_id="property-schedule",
            payload=payload,
        )
        assert activity.edc_visit_instance_id == visit.id
        assert activity.study_id == study.id
        assert activity.site_id == site.id
        assert activity.status == MonitoringActivityStatus.SCHEDULED.value
        assert (edc_state.snapshot(), other_edc_state.snapshot()) == edc_before

        terminal_reached = False
        for index, operation in enumerate(scenario["operations"]):
            before_edc = (edc_state.snapshot(), other_edc_state.snapshot())
            planned, reason, evidence = _apply_operation_data(operation, scenario["day_offset"] + index)
            if terminal_reached:
                with pytest.raises(ConflictError):
                    if operation == "complete":
                        await service.complete_activity(session, activity, evidence=evidence, actor_id=actor.id)
                    elif operation == "cancel":
                        await service.cancel_activity(session, activity, reason=reason, actor_id=actor.id)
                    else:
                        await service.reschedule_activity(session, activity, planned, reason=reason, actor_id=actor.id)
                assert (edc_state.snapshot(), other_edc_state.snapshot()) == before_edc
                continue

            if operation == "reschedule":
                await service.reschedule_activity(
                    session, activity, planned, reason=reason, actor_id=actor.id
                )
            elif operation == "complete":
                await service.complete_activity(
                    session,
                    activity,
                    evidence=evidence,
                    notes="Generated completion note",
                    actor_id=actor.id,
                )
                terminal_reached = True
            else:
                await service.cancel_activity(session, activity, reason=reason, actor_id=actor.id)
                terminal_reached = True
            assert (edc_state.snapshot(), other_edc_state.snapshot()) == before_edc

        assert activity.edc_visit_instance_id == visit.id
        assert session.ctms_snapshot() != ctms_before_command
        assert mutations
        assert (edc_state.snapshot(), other_edc_state.snapshot()) == edc_before
