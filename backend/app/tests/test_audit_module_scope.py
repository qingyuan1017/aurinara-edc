"""Unit tests for module-scoped auditing of auditable actions (Task 18.1).

Validates Requirements:
  - 1.7: A Designer_Definition or Operational_Record change records one
         immutable audit event identifying the OWNING module scope.
  - 10.7: A denied create/modify of a Designer_Definition or Operational_Record
          records exactly one immutable audit event identifying the actor, the
          ATTEMPTED module scope, the attempted action, and the denial.

These are focused unit tests that exercise the shared ``AuditService`` and
``PermissionService.require_audited`` with a lightweight fake session. They do
NOT cover Property 14 (task 18.2), which generalizes the one-event invariant
across all auditable actions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

import pytest

from app.core.audit import AuditService
from app.core.ctms import Module
from app.core.exceptions import AuthorizationError
from app.models.shared.audit import AuditEvent
from app.services.shared.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Fake async session that records what the audit service writes.
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal async session double capturing added AuditEvents.

    ``AuditService.record`` only needs ``add`` and ``flush``; it never commits
    (the caller owns the transaction). We record every added event and count
    commits so the tests can assert exactly-one-event and no-commit behavior.
    """

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
# Lightweight user/role stubs (mirrors test_permission_service style).
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


def _user_without_permission() -> _StubUser:
    """A user whose only role grants an unrelated permission code."""
    role = _StubRole(
        name="Bystander",
        scope_level="system",
        role_permissions=[_StubRolePermission(permission=_StubPermission(code="audit.read"))],
    )
    return _StubUser(user_roles=[_StubUserRole(role=role, study_id=None, site_id=None)])


# ---------------------------------------------------------------------------
# Obligation 1 (R1.7): owning module scope on changes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_designer_change_records_designer_module_scope() -> None:
    """A Designer_Definition change records exactly one event scoped DESIGNER."""
    session = _FakeSession()
    service = AuditService()

    event = await service.record(
        session,
        entity_type="form_definition",
        entity_id=uuid.uuid4(),
        action="create",
        module=Module.DESIGNER,
    )

    assert len(session.added) == 1
    assert session.commit_count == 0
    assert event.module == Module.DESIGNER.value == "DESIGNER"
    assert event.action == "create"


@pytest.mark.asyncio
async def test_operational_change_records_edc_module_scope() -> None:
    """An Operational_Record change records exactly one event scoped EDC."""
    session = _FakeSession()
    service = AuditService()

    event = await service.record(
        session,
        entity_type="form_instance",
        entity_id=uuid.uuid4(),
        action="update",
        module=Module.EDC,
    )

    assert len(session.added) == 1
    assert session.commit_count == 0
    assert event.module == Module.EDC.value == "EDC"
    assert event.action == "update"


@pytest.mark.asyncio
async def test_record_defaults_to_edc_module_scope() -> None:
    """When no module is supplied the owning scope defaults to EDC (operational)."""
    session = _FakeSession()
    service = AuditService()

    event = await service.record(
        session,
        entity_type="field_value",
        entity_id=uuid.uuid4(),
        action="update",
    )

    assert event.module == "EDC"


# ---------------------------------------------------------------------------
# Obligation 2 (R10.7): denial auditing with attempted module scope.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_designer_create_audits_exactly_one_event() -> None:
    """A denied designer-definition create records exactly one denial event.

    The event carries the attempted DESIGNER module scope, the attempted
    action, the actor, and marks the denial. The AuthorizationError is
    re-raised so the request is rejected and no definition is created.
    """
    session = _FakeSession()
    svc = PermissionService()
    user = _user_without_permission()

    with pytest.raises(AuthorizationError):
        await svc.require_audited(
            session,
            user,
            "form.configure",
            module=Module.DESIGNER,
            action="create",
            entity_type="form_definition",
        )

    assert len(session.added) == 1
    assert session.commit_count == 0

    denial = session.added[0]
    assert denial.module == "DESIGNER"
    assert denial.action == "create"
    assert denial.entity_type == "form_definition"
    assert denial.actor_id == user.id
    assert denial.new_value == "authorization-denied"
    assert "form.configure" in (denial.reason or "")


@pytest.mark.asyncio
async def test_denied_operational_modify_audits_attempted_edc_scope() -> None:
    """A denied operational-record modify records one EDC-scoped denial event."""
    session = _FakeSession()
    svc = PermissionService()
    user = _user_without_permission()
    entity_id = uuid.uuid4()
    study_id = uuid.uuid4()

    with pytest.raises(AuthorizationError):
        await svc.require_audited(
            session,
            user,
            "form.enter",
            module=Module.EDC,
            action="update",
            entity_type="form_instance",
            entity_id=entity_id,
            study_id=study_id,
        )

    assert len(session.added) == 1
    denial = session.added[0]
    assert denial.module == "EDC"
    assert denial.action == "update"
    assert denial.entity_type == "form_instance"
    assert denial.entity_id == entity_id
    assert denial.study_id == study_id


@pytest.mark.asyncio
async def test_require_audited_success_writes_no_denial_event() -> None:
    """When authorized, require_audited emits no denial event of its own.

    The mutation's own audit event (R1.7) remains the single event for the
    action; the guard must not add a second, spurious event on success.
    """
    session = _FakeSession()
    svc = PermissionService()
    role = _StubRole(
        name="Form Designer",
        scope_level="system",
        role_permissions=[
            _StubRolePermission(permission=_StubPermission(code="form.configure"))
        ],
    )
    user = _StubUser(user_roles=[_StubUserRole(role=role, study_id=None, site_id=None)])

    await svc.require_audited(
        session,
        user,
        "form.configure",
        module=Module.DESIGNER,
        action="create",
        entity_type="form_definition",
    )

    assert session.added == []
    assert session.commit_count == 0
