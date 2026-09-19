"""Property-based coverage for CTMS operational work management.

**Validates: Requirements 7.1-7.11, 12.1-12.5, 14.5**

Property 9: Work management remains operational and query follow-ups remain
non-clinical.

The test uses a deterministic async in-memory session fake.  It exercises the
real WorkManagementService and its shared audit/history/outbox and notification
primitives without PostgreSQL, workers, network calls, or other external
services.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError, ConflictError, ValidationError
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.models.ctms.work import (
    EscalationStatus,
    OperationalContact,
    OperationalContactStatus,
    OperationalTask,
    OperationalTaskPriority,
    OperationalTaskStatus,
    TaskDependency,
    TaskEscalation,
)
from app.models.identity import User, UserStatus
from app.models.notification import Notification
from app.models.query import Query, QueryStatus, QueryTargetType
from app.models.site import Site
from app.models.study import Study
from app.services.work_management_service import WorkManagementService


class _Rows:
    """Small result facade sufficient for the service's select/scalars calls."""

    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _InMemorySession:
    """Deterministic repository/transaction fake for the property test.

    ``execute`` returns the model collection selected by SQLAlchemy and the
    service performs the identifier/scope filtering itself.  Every ``add`` is
    visible immediately, which makes failed commands easy to prove atomic:
    validation errors occur before any add and therefore cannot leave partial
    CTMS records, history, audit, outbox, or notifications behind.
    """

    def __init__(self, records: dict[type[Any], list[Any]]):
        self.records = records
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    async def execute(self, statement: Any) -> _Rows:
        model = statement.column_descriptions[0].get("entity")
        return _Rows(self.records.get(model, []))

    def add(self, value: Any) -> None:
        self.added.append(value)
        self.records.setdefault(type(value), []).append(value)

    def add_all(self, values: list[Any]) -> None:
        for value in values:
            self.add(value)

    async def delete(self, value: Any) -> None:
        self.deleted.append(value)
        rows = self.records.get(type(value), [])
        if value in rows:
            rows.remove(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


_TOKEN = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_",
    min_size=1,
    max_size=32,
).filter(lambda value: value.strip())
_SAFE_SUMMARY = _TOKEN.map(lambda value: value.strip())
_PROHIBITED_FIELD = st.sampled_from(
    [
        "clinical_data",
        "field_values",
        "source_document",
        "query_message",
        "message_history",
        "clinical_audit_history",
        "raw_event_body",
    ]
)


@st.composite
def work_scenarios(draw: st.DrawFn) -> dict[str, Any]:
    """Generate lifecycle options spanning operational and boundary behavior."""

    return {
        "actor_id": draw(st.uuids()),
        "owner_id": draw(st.uuids()),
        "inactive_owner_id": draw(st.uuids()),
        "study_id": draw(st.uuids()),
        "site_id": draw(st.uuids()),
        "wrong_site_id": draw(st.uuids()),
        "wrong_study_id": draw(st.uuids()),
        "query_id": draw(st.uuids()),
        "priority": draw(st.sampled_from(list(OperationalTaskPriority))),
        "contact_status": draw(
            st.sampled_from(
                [OperationalContactStatus.INACTIVE, OperationalContactStatus.ARCHIVED]
            )
        ),
        "task_status": draw(
            st.sampled_from(
                [
                    OperationalTaskStatus.IN_PROGRESS,
                    OperationalTaskStatus.COMPLETED,
                    OperationalTaskStatus.CANCELLED,
                    OperationalTaskStatus.ARCHIVED,
                ]
            )
        ),
        "summary": draw(_SAFE_SUMMARY),
        "prohibited_field": draw(_PROHIBITED_FIELD),
        "overdue": draw(st.booleans()),
        "escalations_enabled": draw(st.booleans()),
        "escalation_status": draw(
            st.sampled_from(
                [EscalationStatus.IN_PROGRESS, EscalationStatus.RESOLVED, EscalationStatus.CANCELLED]
            )
        ),
        "missing_reason": draw(st.booleans()),
    }


def _records(scenario: dict[str, Any]) -> tuple[_InMemorySession, User, User, Study, Site, Query]:
    actor = User(
        id=scenario["actor_id"],
        email=f"actor-{scenario['actor_id']}@example.test",
        first_name="CTMS",
        last_name="Actor",
        status=UserStatus.active,
    )
    owner = User(
        id=scenario["owner_id"],
        email=f"owner-{scenario['owner_id']}@example.test",
        first_name="Active",
        last_name="Owner",
        status=UserStatus.active,
    )
    inactive_owner = User(
        id=scenario["inactive_owner_id"],
        email=f"inactive-{scenario['inactive_owner_id']}@example.test",
        first_name="Inactive",
        last_name="Owner",
        status=UserStatus.inactive,
    )
    study = Study(
        id=scenario["study_id"],
        study_code=f"WORK-{scenario['study_id']}",
        title="Operational work property study",
        created_by=actor.id,
    )
    site = Site(
        id=scenario["site_id"],
        study_id=study.id,
        site_number="001",
        name="Operational work property site",
    )
    wrong_study = Study(
        id=scenario["wrong_study_id"],
        study_code=f"OTHER-{scenario['wrong_study_id']}",
        title="Out of scope study",
        created_by=actor.id,
    )
    wrong_site = Site(
        id=scenario["wrong_site_id"],
        study_id=wrong_study.id,
        site_number="999",
        name="Out of scope site",
    )
    query = Query(
        id=scenario["query_id"],
        study_id=study.id,
        site_id=site.id,
        target_type=QueryTargetType.subject.value,
        target_id=uuid4(),
        text="RESTRICTED clinical query message must not cross into CTMS",
        status=QueryStatus.open,
        created_by=actor.id,
    )
    records: dict[type[Any], list[Any]] = {
        User: [actor, owner, inactive_owner],
        Study: [study, wrong_study],
        Site: [site, wrong_site],
        Query: [query],
        OperationalTask: [],
        OperationalContact: [],
        TaskDependency: [],
        TaskEscalation: [],
        CTMSStatusHistory: [],
        CTMSOutbox: [],
        AuditEvent: [],
        Notification: [],
    }
    return _InMemorySession(records), actor, owner, study, site, query


def _count(session: _InMemorySession, model: type[Any]) -> int:
    return len(session.records.get(model, []))


def _task_snapshot(task: OperationalTask) -> tuple[Any, ...]:
    return (task.id, task.status, task.owner_id, task.priority, task.due_date, task.query_id)


@given(scenario=work_scenarios())
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_operational_work_lifecycle_is_scoped_atomic_and_non_clinical(
    scenario: dict[str, Any],
):
    """Operational work invariants hold for every generated lifecycle case.

    **Validates: Requirements 7.1-7.11, 12.1-12.5, 14.5**
    """

    session, actor, owner, study, site, query = _records(scenario)
    service = WorkManagementService(escalations_enabled=scenario["escalations_enabled"])
    now = datetime(2025, 1, 15, 12, tzinfo=UTC)
    due_date = now - timedelta(days=1) if scenario["overdue"] else now + timedelta(days=1)
    query_before = (query.id, query.status, query.text, query.closed_at, query.closed_by)

    task = await service.create_task(
        session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Generated operational task",
        description="Operational description only",
        owner_id=owner.id,
        due_date=due_date,
        priority=scenario["priority"],
        correlation_id=str(uuid4()),
    )
    assert task.priority == scenario["priority"].value
    assert task.due_date == due_date
    assert task.status == OperationalTaskStatus.OPEN.value

    # Every successful CTMS mutation has its status/history (when applicable),
    # immutable audit event, and durable outbox record in the same fake unit.
    assert _count(session, CTMSStatusHistory) >= 1
    assert _count(session, AuditEvent) >= 1
    assert _count(session, CTMSOutbox) >= 1
    assert all(item.correlation_id for item in session.records[AuditEvent])
    assert all(item.correlation_id for item in session.records[CTMSOutbox])

    # Status transitions require a reason and reject invalid transitions without
    # changing the task.  Valid generated targets are then applied normally.
    before_transition = _task_snapshot(task)
    if scenario["missing_reason"]:
        with pytest.raises(ValidationError):
            await service.transition_task_status(
                session, task, scenario["task_status"], actor.id, reason="   "
            )
        assert _task_snapshot(task) == before_transition

    await service.transition_task_status(
        session,
        task,
        scenario["task_status"],
        actor.id,
        reason="Property lifecycle transition",
    )
    assert task.status == scenario["task_status"].value

    # Scope and active-user checks happen before persistence, so rejected
    # commands cannot leave operational, audit, history, outbox, or notification
    # records behind.
    task_count = _count(session, OperationalTask)
    audit_count = _count(session, AuditEvent)
    outbox_count = _count(session, CTMSOutbox)
    with pytest.raises(ConflictError):
        await service.create_task(
            session,
            actor_id=actor.id,
            study_id=study.id,
            site_id=scenario["wrong_site_id"],
            title="Out of scope task",
            owner_id=owner.id,
        )
    assert (_count(session, OperationalTask), _count(session, AuditEvent), _count(session, CTMSOutbox)) == (
        task_count,
        audit_count,
        outbox_count,
    )
    with pytest.raises(ConflictError, match="inactive"):
        await service.create_task(
            session,
            actor_id=actor.id,
            study_id=study.id,
            site_id=site.id,
            title="Inactive owner task",
            owner_id=scenario["inactive_owner_id"],
        )
    assert (_count(session, OperationalTask), _count(session, AuditEvent), _count(session, CTMSOutbox)) == (
        task_count,
        audit_count,
        outbox_count,
    )

    # Query follow-ups retain only the approved summary and canonical query ID;
    # the EDC Query status and complete message text remain untouched.
    follow_up = await service.create_query_follow_up(
        session,
        query_id=query.id,
        actor_id=actor.id,
        owner_id=owner.id,
        approved_summary=scenario["summary"],
        due_date=due_date,
        priority=scenario["priority"],
        correlation_id=str(uuid4()),
    )
    assert follow_up.query_id == query.id
    assert follow_up.query_summary == scenario["summary"]
    assert follow_up.description == "Operational follow-up for an EDC Query"
    assert "RESTRICTED clinical query message" not in repr(follow_up)
    assert query_before == (query.id, query.status, query.text, query.closed_at, query.closed_by)
    await service.transition_task_status(
        session,
        follow_up,
        OperationalTaskStatus.COMPLETED,
        actor.id,
        reason="Follow-up completed",
    )
    assert follow_up.query_id == query.id

    # Contacts use the same scoped active-user and reasoned status lifecycle.
    contact = await service.create_contact(
        session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        name="Generated operational contact",
        role="Coordinator",
        organization="Operations",
        owner_id=owner.id,
    )
    await service.transition_contact_status(
        session,
        contact,
        scenario["contact_status"],
        actor.id,
        reason="Contact lifecycle transition",
    )
    assert contact.status == scenario["contact_status"].value

    # Dependency links block downstream work, reject cycles, and cascade
    # unblocking only after every prerequisite reaches a terminal state.
    dependent = await service.create_task(
        session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Dependent task",
        owner_id=owner.id,
    )
    prerequisite = await service.create_task(
        session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Prerequisite task",
        owner_id=owner.id,
    )
    tail = await service.create_task(
        session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title="Tail prerequisite",
        owner_id=owner.id,
    )
    await service.add_dependency(session, dependent, prerequisite, actor.id, reason="Needs prerequisite")
    await service.add_dependency(session, prerequisite, tail, actor.id, reason="Needs tail")
    assert dependent.status == OperationalTaskStatus.BLOCKED.value
    assert prerequisite.status == OperationalTaskStatus.BLOCKED.value
    with pytest.raises(ConflictError, match="cycle"):
        await service.add_dependency(session, tail, dependent, actor.id, reason="Would create cycle")
    assert _count(session, TaskDependency) == 2
    await service.transition_task_status(session, tail, OperationalTaskStatus.COMPLETED, actor.id, reason="Tail complete")
    assert prerequisite.status == OperationalTaskStatus.OPEN.value
    await service.transition_task_status(
        session, prerequisite, OperationalTaskStatus.COMPLETED, actor.id, reason="Prerequisite complete"
    )
    assert dependent.status == OperationalTaskStatus.OPEN.value

    # Prohibited clinical keys are rejected before a task can be added.
    prohibited_count = _count(session, OperationalTask)
    with pytest.raises(ValidationError, match="prohibited clinical content"):
        await service.create_task(
            session,
            actor_id=actor.id,
            study_id=study.id,
            site_id=site.id,
            title="Rejected clinical payload",
            owner_id=owner.id,
            **{scenario["prohibited_field"]: "clinical secret"},
        )
    assert _count(session, OperationalTask) == prohibited_count

    # Escalations are environment-gated, reasoned, and operational.  A single
    # reminder pass is bounded by the number of non-terminal owned tasks.
    escalation_payload = {
        "task_id": dependent.id,
        "owner_id": owner.id,
        "reason": "Generated deadline risk",
        "deadline": now + timedelta(days=1),
    }
    if scenario["escalations_enabled"]:
        escalation = await service.create_escalation(
            session, escalation_payload, actor.id, correlation_id=str(uuid4())
        )
        await service.transition_escalation_status(
            session,
            escalation,
            scenario["escalation_status"],
            actor.id,
            reason="Escalation lifecycle transition",
        )
        assert escalation.status == scenario["escalation_status"].value
    else:
        with pytest.raises(BusinessRuleError, match="disabled"):
            await service.create_escalation(session, escalation_payload, actor.id)
        assert _count(session, TaskEscalation) == 0

    before_notifications = _count(session, Notification)
    reminder_count = await service.process_reminders(session, now=now, actor_id=actor.id)
    active_owned_tasks = [
        item
        for item in session.records[OperationalTask]
        if item.owner_id is not None
        and item.status not in {
            OperationalTaskStatus.COMPLETED.value,
            OperationalTaskStatus.CANCELLED.value,
            OperationalTaskStatus.ARCHIVED.value,
        }
    ]
    expected_reminders = sum(
        1
        for item in active_owned_tasks
        if (item.due_date is not None and item.due_date <= now)
        or item.status == OperationalTaskStatus.BLOCKED.value
    )
    assert reminder_count == expected_reminders
    assert 0 <= reminder_count <= len(active_owned_tasks)
    assert _count(session, Notification) - before_notifications == reminder_count
    assert all(
        notification.type in {"ctms_task_overdue", "ctms_task_dependency_reminder"}
        for notification in session.records[Notification][before_notifications:]
    )

    # The final EDC snapshot and all successful CTMS bookkeeping remain intact.
    assert query_before == (query.id, query.status, query.text, query.closed_at, query.closed_by)
    assert _count(session, AuditEvent) == _count(session, CTMSOutbox)
    assert _count(session, CTMSStatusHistory) >= 1
