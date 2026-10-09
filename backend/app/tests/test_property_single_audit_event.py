"""Property-based test for exactly-one immutable audit event per auditable action.

# Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

**Validates: Requirements 1.7, 10.7, 11.7**

Property 14 (design.md): _For all_ changes to a Designer_Definition or
Operational_Record, all authorization denials, and all migration reassignments,
the Audit_Service records exactly one immutable (append-only) audit event
identifying the owning/attempted module scope, the actor, the entity, the
action/change, and the timestamp.

This test generalizes the one-event invariant established by the focused unit
tests in ``test_audit_module_scope.py`` (task 18.1) across every auditable
action, driven with Hypothesis over three auditable-action families:

1. A **change** (create/update/delete) to a Designer_Definition
   (``Module.DESIGNER``) or an Operational_Record (``Module.EDC``), recorded
   through ``audit_service.record`` (R1.7).
2. An **authorization denial** of such a create/modify, recorded exactly once
   through ``PermissionService.require_audited`` (R10.7). An *authorized*
   ``require_audited`` adds zero events of its own (the mutation's own change
   event is the single event for the action).
3. A **migration reassignment**, recorded as one event carrying the
   source/target module scope through ``audit_service.record`` (R11.7).

Every assertion verifies: exactly one event is appended per auditable action
(zero on an authorized ``require_audited``), the event carries the expected
module scope, action, actor and a timezone-aware timestamp, and the
``AuditService`` exposes no mutation (update/delete) path (append-only
immutability).
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.audit import AuditService, audit_service
from app.core.ctms import Module
from app.core.exceptions import AuthorizationError
from app.models.shared.audit import AuditEvent
from app.services.shared.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Fake async session that records what the audit service writes.
# Mirrors ``test_audit_module_scope.py`` so the property generalizes the same
# contract: ``AuditService.record`` only needs ``add`` and ``flush`` and never
# commits (the caller owns the transaction).
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal async session double capturing added AuditEvents."""

    def __init__(self) -> None:
        self.added: list[AuditEvent] = []
        self.flush_count = 0
        self.commit_count = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)  # type: ignore[arg-type]

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:  # pragma: no cover - must never be called
        self.commit_count += 1


# ---------------------------------------------------------------------------
# Lightweight user/role stubs (mirrors test_audit_module_scope.py style).
# ---------------------------------------------------------------------------


@dataclass
class _StubPermission:
    code: str
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class _StubRolePermission:
    permission: _StubPermission
    role_id: UUID = field(default_factory=uuid.uuid4)
    permission_id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class _StubRole:
    name: str
    scope_level: str
    role_permissions: list[_StubRolePermission] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class _StubUserRole:
    role: _StubRole
    study_id: UUID | None = None
    site_id: UUID | None = None
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class _StubUser:
    user_roles: list[_StubUserRole] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)
    email: str = "actor@example.com"
    status: str = "active"


def _user_with(permission_codes: list[str]) -> _StubUser:
    """Build a system-scope user granting exactly ``permission_codes``."""
    role = _StubRole(
        name="Generated",
        scope_level="system",
        role_permissions=[
            _StubRolePermission(permission=_StubPermission(code=code))
            for code in permission_codes
        ],
    )
    return _StubUser(user_roles=[_StubUserRole(role=role, study_id=None, site_id=None)])


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A Designer_Definition change carries Module.DESIGNER; an Operational_Record
# change carries Module.EDC. Both are auditable "change" actions.
_module_strategy = st.sampled_from([Module.DESIGNER, Module.EDC])

_action_strategy = st.sampled_from(["create", "update", "delete"])

_designer_entity_strategy = st.sampled_from(
    ["form_definition", "field_definition", "visit_definition", "codelist", "edit_check"]
)
_operational_entity_strategy = st.sampled_from(
    ["subject", "visit_instance", "form_instance", "form_record", "field_value"]
)


@st.composite
def _change_strategy(draw):
    """Generate a change to a Designer_Definition or an Operational_Record."""
    module = draw(_module_strategy)
    entity_type = draw(
        _designer_entity_strategy
        if module is Module.DESIGNER
        else _operational_entity_strategy
    )
    return {
        "module": module,
        "entity_type": entity_type,
        "entity_id": draw(st.uuids()),
        "action": draw(_action_strategy),
        "actor_id": draw(st.uuids()),
    }


@st.composite
def _reassignment_strategy(draw):
    """Generate a migration reassignment between modules."""
    source = draw(_module_strategy)
    target = draw(_module_strategy)
    return {
        "entity_type": draw(
            st.sampled_from(["study_version", "form_definition", "subject", "form_instance"])
        ),
        "entity_id": draw(st.uuids()),
        "source_module": source,
        "target_module": target,
        "actor_id": draw(st.uuids()),
    }


# ---------------------------------------------------------------------------
# Property 14 — exactly one immutable audit event per auditable action.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(change=_change_strategy())
async def test_change_records_exactly_one_scoped_event(change) -> None:
    """A Designer/Operational change records exactly one owning-scope event.

    # Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

    **Validates: Requirements 1.7**
    """
    session = _FakeSession()
    service = AuditService()

    event = await service.record(
        session,
        entity_type=change["entity_type"],
        entity_id=change["entity_id"],
        action=change["action"],
        module=change["module"],
        actor_id=change["actor_id"],
    )

    # Exactly one immutable event is appended; the caller owns the transaction.
    assert len(session.added) == 1
    assert session.added[0] is event
    assert session.commit_count == 0

    # The event carries the owning module scope, action, entity and actor.
    assert event.module == change["module"].value
    assert event.action == change["action"]
    assert event.entity_type == change["entity_type"]
    assert event.entity_id == change["entity_id"]
    assert event.actor_id == change["actor_id"]
    # And a timezone-aware timestamp (R1.7 "timestamp").
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None


@settings(max_examples=100, deadline=None)
@given(change=_change_strategy())
async def test_denied_change_records_exactly_one_denial_event(change) -> None:
    """A denied create/modify records exactly one attempted-scope denial event.

    # Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

    **Validates: Requirements 10.7**
    """
    session = _FakeSession()
    svc = PermissionService()
    # A user whose only grant is unrelated — the required permission is denied.
    user = _user_with(["audit.read"])
    required_permission = "module.author"

    with pytest.raises(AuthorizationError):
        await svc.require_audited(
            session,
            user,
            required_permission,
            module=change["module"],
            action=change["action"],
            entity_type=change["entity_type"],
            entity_id=change["entity_id"],
        )

    # Exactly one immutable denial event; nothing else is committed because the
    # permission check runs before any mutation.
    assert len(session.added) == 1
    assert session.commit_count == 0

    denial = session.added[0]
    assert denial.module == change["module"].value
    assert denial.action == change["action"]
    assert denial.entity_type == change["entity_type"]
    assert denial.entity_id == change["entity_id"]
    assert denial.actor_id == user.id
    assert denial.new_value == "authorization-denied"
    assert required_permission in (denial.reason or "")
    assert isinstance(denial.timestamp, datetime)
    assert denial.timestamp.tzinfo is not None


@settings(max_examples=100, deadline=None)
@given(change=_change_strategy())
async def test_authorized_change_adds_no_denial_event(change) -> None:
    """An authorized require_audited emits zero events of its own.

    # Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

    The mutation's own change event (R1.7) is the single event for the action;
    the guard must not add a second, spurious event on success.

    **Validates: Requirements 10.7**
    """
    session = _FakeSession()
    svc = PermissionService()
    required_permission = "module.author"
    user = _user_with([required_permission])

    await svc.require_audited(
        session,
        user,
        required_permission,
        module=change["module"],
        action=change["action"],
        entity_type=change["entity_type"],
        entity_id=change["entity_id"],
    )

    # Zero events: the authorized guard never writes a denial event.
    assert session.added == []
    assert session.commit_count == 0


@settings(max_examples=100, deadline=None)
@given(reassignment=_reassignment_strategy())
async def test_migration_reassignment_records_exactly_one_event(reassignment) -> None:
    """A migration reassignment records exactly one scoped, immutable event.

    # Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

    **Validates: Requirements 11.7**
    """
    session = _FakeSession()
    service = AuditService()

    event = await service.record(
        session,
        entity_type=reassignment["entity_type"],
        entity_id=reassignment["entity_id"],
        action="reassign",
        module=reassignment["target_module"],
        source_module=reassignment["source_module"],
        target_module=reassignment["target_module"],
        source_record_id=reassignment["entity_id"],
        target_record_id=reassignment["entity_id"],
        actor_id=reassignment["actor_id"],
    )

    # Exactly one immutable reassignment event; no commit (caller's tx).
    assert len(session.added) == 1
    assert session.added[0] is event
    assert session.commit_count == 0

    # The event carries the source/target module scope and the action.
    assert event.action == "reassign"
    assert event.module == reassignment["target_module"].value
    assert event.source_module == reassignment["source_module"].value
    assert event.target_module == reassignment["target_module"].value
    assert event.entity_id == reassignment["entity_id"]
    assert event.actor_id == reassignment["actor_id"]
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None


@settings(max_examples=100, deadline=None)
@given(
    kind=st.sampled_from(["change", "denial", "reassignment"]),
    change=_change_strategy(),
    reassignment=_reassignment_strategy(),
)
async def test_every_auditable_action_appends_exactly_one_or_zero(
    kind, change, reassignment
) -> None:
    """Across all auditable-action families, each action appends 1 (or 0) event.

    # Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

    A change appends exactly one event, a denial appends exactly one event, and
    an authorized guard appends zero — never two events for a single action.

    **Validates: Requirements 1.7, 10.7, 11.7**
    """
    session = _FakeSession()
    service = AuditService()
    svc = PermissionService()

    if kind == "change":
        await service.record(
            session,
            entity_type=change["entity_type"],
            entity_id=change["entity_id"],
            action=change["action"],
            module=change["module"],
            actor_id=change["actor_id"],
        )
        assert len(session.added) == 1
    elif kind == "reassignment":
        await service.record(
            session,
            entity_type=reassignment["entity_type"],
            entity_id=reassignment["entity_id"],
            action="reassign",
            module=reassignment["target_module"],
            source_module=reassignment["source_module"],
            target_module=reassignment["target_module"],
            actor_id=reassignment["actor_id"],
        )
        assert len(session.added) == 1
    else:  # denial
        user = _user_with(["audit.read"])
        with pytest.raises(AuthorizationError):
            await svc.require_audited(
                session,
                user,
                "module.author",
                module=change["module"],
                action=change["action"],
                entity_type=change["entity_type"],
                entity_id=change["entity_id"],
            )
        assert len(session.added) == 1

    # Never more than one event for a single auditable action, never a commit.
    assert len(session.added) <= 1
    assert session.commit_count == 0


# ---------------------------------------------------------------------------
# Immutability: the audit service exposes no mutation (update/delete) path.
# ---------------------------------------------------------------------------


def test_audit_service_exposes_no_mutation_method() -> None:
    """AuditService exposes only append/read methods — no update/delete path.

    # Feature: designer-edc-refactor, Property 14: Exactly one immutable audit event per auditable action

    **Validates: Requirements 1.7, 10.7, 11.7**
    """
    service = AuditService()

    for forbidden in ("update", "delete", "remove", "modify", "edit", "save"):
        assert not hasattr(service, forbidden), (
            f"AuditService must not expose a '{forbidden}' method (immutability)"
        )

    allowed = {"record", "search", "export"}
    public_methods = {
        name
        for name, _ in inspect.getmembers(service, predicate=inspect.ismethod)
        if not name.startswith("_")
    }
    disallowed = public_methods - allowed
    assert disallowed == set(), (
        f"AuditService has disallowed public methods: {disallowed}. "
        f"Only {allowed} are permitted for append-only immutability."
    )

    # The module-level singleton must honor the same contract.
    for forbidden in ("update", "delete", "remove", "modify"):
        assert not hasattr(audit_service, forbidden)
