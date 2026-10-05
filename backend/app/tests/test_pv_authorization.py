"""PV/Safety authorization: roles, permission seeds, and dependency guards.

Feature: pv-safety-module, Task 1.4
Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 18.4

These tests confirm that PV reuses the shared Auth_Service/Permission_Service:
  - PV permission codes and roles are defined in the shared authorization
    namespace and composed only from PV_PERMISSION_CODES;
  - no PV role can mutate an EDC clinical or CTMS operational record;
  - PV dependency guards resolve the required permission and target scope
    before a mutation, deny out-of-scope/after-scope-removal actions with a
    non-disclosing indication, and reject inactive users.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from app.api.deps import require_pv_object_access, require_pv_permission
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import (
    CTMS_PERMISSION_CODES,
    PERMISSION_CODES,
    PV_PERMISSION_CODES,
    ROLE_DEFINITIONS,
)
from app.schemas.permission import (
    PV_PERMISSION_ALIASES,
    AuthorizationScope,
    PermissionGrant,
    normalize_permission_code,
)
from app.services.permission_service import PermissionService

STUDY_A = uuid.uuid4()
STUDY_B = uuid.uuid4()
SITE_1 = uuid.uuid4()
SITE_2 = uuid.uuid4()

# EDC clinical and CTMS operational mutation permissions PV must never hold.
_EDC_CLINICAL_MUTATIONS = {
    "study.create",
    "study.configure",
    "version.publish",
    "site.manage",
    "subject.create",
    "subject.update",
    "form.configure",
    "form.enter",
    "form.submit",
    "query.create",
    "query.respond",
    "query.close",
    "query.reopen",
    "query.cancel",
    "editcheck.configure",
    "sdv.manage",
    "review.manage",
    "lock.manage",
    "signature.sign",
    "file.upload",
}

_PV_ROLE_NAMES = {
    "Safety_Admin",
    "Safety_Manager",
    "Safety_Associate",
    "Safety_Physician",
    "Safety_Coder",
    "Regulatory_Reporter",
    "Safety_Viewer",
}


# ---------------------------------------------------------------------------
# Lightweight identity stubs (mirror the shared guard test doubles)
# ---------------------------------------------------------------------------


@dataclass
class StubPermission:
    code: str
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubRolePermission:
    permission: StubPermission
    role_id: UUID = field(default_factory=uuid.uuid4)
    permission_id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubRole:
    name: str
    scope_level: str
    role_permissions: list[StubRolePermission] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubUserRole:
    role: StubRole
    study_id: UUID | None = None
    site_id: UUID | None = None
    user_id: UUID = field(default_factory=uuid.uuid4)
    role_id: UUID = field(default_factory=uuid.uuid4)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubUser:
    user_roles: list[StubUserRole] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)
    email: str = "safety@example.com"
    status: str = "active"


@dataclass
class StubRequest:
    path_params: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)


@dataclass
class StubObject:
    study_id: UUID | None = None
    site_id: UUID | None = None


def _pv_user(role_name: str, study_id: UUID | None, site_id: UUID | None) -> StubUser:
    """Build a user carrying a seeded PV role at the given scope."""
    definition = ROLE_DEFINITIONS[role_name]
    perms = [
        StubRolePermission(permission=StubPermission(code=code))
        for code in definition["permissions"]
    ]
    role = StubRole(
        name=role_name, scope_level=definition["scope"], role_permissions=perms
    )
    return StubUser(user_roles=[StubUserRole(role=role, study_id=study_id, site_id=site_id)])


# ---------------------------------------------------------------------------
# Permission codes and role definitions
# ---------------------------------------------------------------------------


class TestPVPermissionCodes:
    def test_pv_permission_namespace_is_registered(self):
        # Every PV code is part of the shared permission namespace.
        assert PV_PERMISSION_CODES <= PERMISSION_CODES

    def test_task_named_pv_permissions_present(self):
        for code in (
            "safety_case.enter",
            "safety_assessment.record",
            "safety_coding.assign",
            "safety_narrative.write",
            "safety_report.manage",
            "safety_reconciliation.run",
            "safety_export.create",
            "safety_audit.read",
        ):
            assert code in PV_PERMISSION_CODES

    def test_pv_and_ctms_namespaces_are_disjoint(self):
        assert PV_PERMISSION_CODES.isdisjoint(CTMS_PERMISSION_CODES)

    def test_pv_aliases_resolve_to_stored_codes(self):
        for alias, code in PV_PERMISSION_ALIASES.items():
            assert normalize_permission_code(alias) == code
            assert code in PV_PERMISSION_CODES


class TestPVRoleDefinitions:
    def test_all_pv_roles_seeded(self):
        assert set(ROLE_DEFINITIONS) >= _PV_ROLE_NAMES

    def test_pv_roles_only_hold_pv_permissions(self):
        # Requirement 2.6 / 18.4: PV roles cannot mutate EDC/CTMS records.
        for name in _PV_ROLE_NAMES:
            perms = set(ROLE_DEFINITIONS[name]["permissions"])
            assert perms <= PV_PERMISSION_CODES, name
            assert perms.isdisjoint(_EDC_CLINICAL_MUTATIONS), name
            assert perms.isdisjoint(CTMS_PERMISSION_CODES), name

    def test_safety_admin_holds_all_pv_permissions(self):
        assert set(ROLE_DEFINITIONS["Safety_Admin"]["permissions"]) >= PV_PERMISSION_CODES
        assert ROLE_DEFINITIONS["Safety_Admin"]["scope"] == "system"

    def test_safety_viewer_is_read_only(self):
        viewer = set(ROLE_DEFINITIONS["Safety_Viewer"]["permissions"])
        assert viewer == {"safety_case.read", "safety_audit.read"}
        # No enter/lifecycle/assessment/coding/report/reconciliation/export.
        mutating = PV_PERMISSION_CODES - {"safety_case.read", "safety_audit.read"}
        assert viewer.isdisjoint(mutating)

    def test_safety_associate_is_site_scoped(self):
        assert ROLE_DEFINITIONS["Safety_Associate"]["scope"] == "site"

    def test_system_administrator_still_holds_pv_permissions(self):
        # System Administrator is derived from PERMISSION_CODES, so adding PV
        # codes automatically extends the platform admin.
        admin = set(ROLE_DEFINITIONS["System Administrator"]["permissions"])
        assert admin >= PV_PERMISSION_CODES


# ---------------------------------------------------------------------------
# require_pv_permission guard (route-level scope)
# ---------------------------------------------------------------------------


class TestRequirePVPermissionGuard:
    @pytest.mark.asyncio
    async def test_grants_in_scope_action(self):
        user = _pv_user("Safety_Manager", STUDY_A, None)
        request = StubRequest(path_params={"study_id": str(STUDY_A)})
        guard = require_pv_permission("safety_case.enter")
        result = await guard(
            request=request, current_user=user, permission_service=PermissionService()
        )
        assert result is user

    @pytest.mark.asyncio
    async def test_denies_missing_permission_without_disclosure(self):
        # Viewer lacks safety_case.enter.
        user = _pv_user("Safety_Viewer", STUDY_A, None)
        request = StubRequest(path_params={"study_id": str(STUDY_A)})
        guard = require_pv_permission("safety_case.enter")
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(
                request=request, current_user=user, permission_service=PermissionService()
            )
        details = exc_info.value.details
        assert details["reason"] == "PV_SCOPE_DENIED"
        # Non-disclosing: no study/site or object existence is revealed.
        assert "study_id" not in details
        assert "site_id" not in details

    @pytest.mark.asyncio
    async def test_denies_out_of_scope_study(self):
        user = _pv_user("Safety_Manager", STUDY_A, None)
        request = StubRequest(path_params={"study_id": str(STUDY_B)})
        guard = require_pv_permission("safety_case.enter")
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(
                request=request, current_user=user, permission_service=PermissionService()
            )
        assert exc_info.value.details["reason"] == "PV_SCOPE_DENIED"

    @pytest.mark.asyncio
    async def test_denies_site_action_after_scope_removal(self):
        # A site-scoped associate loses access once its site grant is removed;
        # scope is resolved live from current role assignments (Requirement 2.x).
        user = _pv_user("Safety_Associate", STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        guard = require_pv_permission("safety_case.enter")
        # Initially allowed.
        assert (
            await guard(
                request=request,
                current_user=user,
                permission_service=PermissionService(),
            )
            is user
        )
        # Scope removed.
        user.user_roles = []
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(
                request=request, current_user=user, permission_service=PermissionService()
            )
        assert exc_info.value.details["reason"] == "PV_SCOPE_DENIED"

    @pytest.mark.asyncio
    async def test_rejects_inactive_user(self):
        # Requirement 1.4 / 2.x: inactive accounts are rejected before mutation.
        user = _pv_user("Safety_Manager", STUDY_A, None)
        user.status = "inactive"
        request = StubRequest(path_params={"study_id": str(STUDY_A)})
        guard = require_pv_permission("safety_case.enter")
        with pytest.raises(AuthenticationError, match="inactive"):
            await guard(
                request=request, current_user=user, permission_service=PermissionService()
            )


# ---------------------------------------------------------------------------
# require_pv_object_access guard (object-level scope)
# ---------------------------------------------------------------------------


class TestRequirePVObjectAccessGuard:
    @pytest.mark.asyncio
    async def test_grants_access_to_in_scope_object(self):
        user = _pv_user("Safety_Manager", STUDY_A, None)
        obj = StubObject(study_id=STUDY_A, site_id=SITE_1)

        async def _getter() -> StubObject:
            return obj

        guard = require_pv_object_access("safety_case.read", _getter)
        result = await guard(
            current_user=user, permission_service=PermissionService(), obj=obj
        )
        assert result is user

    @pytest.mark.asyncio
    async def test_denies_out_of_scope_object_without_disclosure(self):
        # Study A manager cannot read a Study B case; must not reveal existence.
        user = _pv_user("Safety_Manager", STUDY_A, None)
        obj = StubObject(study_id=STUDY_B, site_id=SITE_2)

        async def _getter() -> StubObject:
            return obj

        guard = require_pv_object_access("safety_case.read", _getter)
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(
                current_user=user, permission_service=PermissionService(), obj=obj
            )
        assert exc_info.value.details["reason"] == "PV_SCOPE_DENIED"


# ---------------------------------------------------------------------------
# Scope resolution / list filtering (Requirement 2.3)
# ---------------------------------------------------------------------------


class TestPVScopeResolution:
    def test_resolves_pv_scope_from_role(self):
        user = _pv_user("Safety_Manager", STUDY_A, None)
        scope = PermissionService().resolve_scope(user)
        assert scope.has_permission("safety_case.enter", study_id=STUDY_A)
        assert not scope.has_permission("safety_case.enter", study_id=STUDY_B)

    def test_list_filter_returns_only_in_scope_studies(self):
        user = _pv_user("Safety_Manager", STUDY_A, None)
        svc = PermissionService()
        assert svc.filter_studies(user, [STUDY_A, STUDY_B]) == [STUDY_A]

    def test_scope_uses_alias_form(self):
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(permission_code="safety_case.enter", study_id=STUDY_A)
            ]
        )
        assert scope.has_permission("safety-case-enter", study_id=STUDY_A)
