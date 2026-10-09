"""Property-based test for module-scoped separation of duties with default-deny.

# Feature: designer-edc-refactor, Property 13: Module-scoped separation of duties with default-deny

**Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6**

Property 13 (design.md): _For all_ users (holding a Designer_Role only, an
Operational_Role only, both, or neither) and all permission codes (sampled from
the Designer_Module set, the EDC_Module operational set, and shared/platform
codes), server-side authorization is module-scoped and defaults to deny:

  - A designer-module permission is granted only through a role that owns the
    designer module; an operational-module permission only through a role that
    owns the operational module (R10.2, R10.3).
  - A user holding exactly one of Designer_Role / Operational_Role is granted
    only that module's permissions and denied every permission of the other
    module (R10.5).
  - A user holding both roles can exercise each module's permissions only within
    its own module scope — one role never authorizes the other module's action,
    yet neither role leaks: a both-role user is allowed designer AND operational
    codes, each via its own role (R10.6).
  - A module-scoped permission with no owning-role grant is denied (default-deny,
    R10.4).

The authority under test is the real
``app.services.shared.permission_service.PermissionService`` enforcing against
the real ``AuthorizationScope`` module gate — no mocking of the authorization
logic. Only lightweight ORM-shaped stubs stand in for the SQLAlchemy User/Role
graph, mirroring the stub-user builders in ``test_permission_service.py``.

The oracle for every assertion is derived independently from the static module
classification (``permission_module`` / ``role_modules``), so the test never
re-implements the service under test: it computes the module a code belongs to
and the modules the user's roles own, then asserts grant/deny follows the
module-scoped default-deny matrix exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import AuthorizationError
from app.core.permissions import (
    DESIGNER_PERMISSION_CODES,
    OPERATIONAL_PERMISSION_CODES,
    permission_module,
)
from app.services.shared.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Lightweight stubs for ORM objects (mirrors test_permission_service.py so the
# service resolves scope from a realistic User -> UserRole -> Role -> Permission
# graph without a database).
# ---------------------------------------------------------------------------


@dataclass
class StubPermission:
    """Stub for Permission model."""

    code: str
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubRolePermission:
    """Stub for RolePermission model."""

    permission: StubPermission
    role_id: UUID = field(default_factory=uuid.uuid4)
    permission_id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubRole:
    """Stub for Role model."""

    name: str
    scope_level: str
    role_permissions: list[StubRolePermission] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubUserRole:
    """Stub for UserRole model."""

    role: StubRole
    study_id: UUID | None = None
    site_id: UUID | None = None
    user_id: UUID = field(default_factory=uuid.uuid4)
    role_id: UUID = field(default_factory=uuid.uuid4)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubUser:
    """Stub for User model."""

    user_roles: list[StubUserRole] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)
    email: str = "test@example.com"
    status: str = "active"


# A single study the roles are scoped to, matched on every require() call so
# scope resolution never spuriously denies for a study mismatch (scope matching
# is covered by test_permission_service.py; this suite isolates the module gate).
STUDY = uuid.uuid4()


def _role_with(name: str, codes: list[str]) -> StubRole:
    """Build a study-scoped StubRole granting the given permission codes."""
    perms = [StubRolePermission(permission=StubPermission(code=c)) for c in codes]
    return StubRole(name=name, scope_level="study", role_permissions=perms)


def _make_designer_user() -> StubUser:
    """User holding only a Designer_Role (full designer-module code set)."""
    role = _role_with("Designer_Role", sorted(DESIGNER_PERMISSION_CODES))
    return StubUser(user_roles=[StubUserRole(role=role, study_id=STUDY)])


def _make_operational_user() -> StubUser:
    """User holding only an Operational_Role (full operational-module code set)."""
    role = _role_with("Operational_Role", sorted(OPERATIONAL_PERMISSION_CODES))
    return StubUser(user_roles=[StubUserRole(role=role, study_id=STUDY)])


def _make_both_role_user() -> StubUser:
    """User holding both a Designer_Role and an Operational_Role on one study."""
    designer_role = _role_with("Designer_Role", sorted(DESIGNER_PERMISSION_CODES))
    operational_role = _role_with(
        "Operational_Role", sorted(OPERATIONAL_PERMISSION_CODES)
    )
    return StubUser(
        user_roles=[
            StubUserRole(role=designer_role, study_id=STUDY),
            StubUserRole(role=operational_role, study_id=STUDY),
        ]
    )


def _make_neither_user() -> StubUser:
    """User holding no module role at all (default-deny baseline)."""
    return StubUser(user_roles=[])


# Profiles the user may take. Each maps to the set of modules its roles own, so
# the oracle for module ownership is independent of the service under test.
_USER_PROFILES: dict[str, tuple] = {
    # name -> (builder, owned_modules)
    "designer_only": (_make_designer_user, frozenset({"designer"})),
    "operational_only": (_make_operational_user, frozenset({"operational"})),
    "both": (_make_both_role_user, frozenset({"designer", "operational"})),
    "neither": (_make_neither_user, frozenset()),
}

# Shared/platform codes classify to module None and are exempt from the module
# gate; include a representative sample so the strategy also exercises the
# "not module-scoped" branch.
_SHARED_CODES: tuple[str, ...] = (
    "user.list",
    "audit.read",
    "ctms.operational_data_read",
    "safety_case.read",
)

# All codes the strategy may require: every designer code, every operational
# code, and a sample of shared codes.
_ALL_CODES: tuple[str, ...] = (
    *sorted(DESIGNER_PERMISSION_CODES),
    *sorted(OPERATIONAL_PERMISSION_CODES),
    *_SHARED_CODES,
)

profile_strategy = st.sampled_from(sorted(_USER_PROFILES))
code_strategy = st.sampled_from(_ALL_CODES)

# PermissionService is stateless, so a single module-level instance is reused
# across all generated inputs (avoids the function-scoped-fixture health check
# that Hypothesis raises for a per-test fixture under @given).
_SVC = PermissionService()


def _expected_grant(owned_modules: frozenset[str], code: str) -> bool:
    """Independent oracle: should authorization succeed for this user/code?

    A module-scoped code (designer/operational) is granted iff the user's roles
    own that module. A shared code (module None) is NOT in the designer/
    operational role sets used by these profiles, so for the profiles here it is
    never granted — the module gate only exempts shared codes from the *module*
    constraint, it does not conjure a grant the user never held. All four
    profiles here grant only designer and/or operational codes, so a shared code
    is always denied (the user simply does not hold it).
    """
    module = permission_module(code)
    if module is None:
        # Shared code: none of these profiles' roles grant shared codes, so the
        # permission is simply absent -> denied.
        return False
    return module in owned_modules


class TestModuleScopedSeparationOfDutiesProperty:
    """Property 13 — module-scoped SoD with default-deny holds for all users/codes.

    # Feature: designer-edc-refactor, Property 13: Module-scoped separation of duties with default-deny

    **Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6**
    """

    @settings(max_examples=300, deadline=None)
    @given(profile=profile_strategy, code=code_strategy)
    def test_require_matches_module_scoped_matrix(self, profile: str, code: str):
        """``require`` grants iff the user's roles own the code's module.

        Covers R10.2/R10.3 (module code effective only via owning role),
        R10.4 (default-deny when ownership is absent), R10.5 (single-role users
        confined to one module), and R10.6 (both-role users satisfy each module
        only via its own role).
        """
        builder, owned_modules = _USER_PROFILES[profile]
        user = builder()
        expected = _expected_grant(owned_modules, code)

        if expected:
            # Must not raise for a code whose module the user's roles own.
            _SVC.require(user, code, study_id=STUDY)
        else:
            with pytest.raises(AuthorizationError):
                _SVC.require(user, code, study_id=STUDY)

    @settings(max_examples=300, deadline=None)
    @given(profile=profile_strategy, code=code_strategy)
    def test_has_permission_matches_module_scoped_matrix(
        self, profile: str, code: str
    ):
        """``AuthorizationScope.has_permission`` agrees with the SoD matrix."""
        builder, owned_modules = _USER_PROFILES[profile]
        user = builder()
        scope = _SVC.resolve_scope(user)
        expected = _expected_grant(owned_modules, code)

        assert scope.has_permission(code, study_id=STUDY) is expected

    @settings(max_examples=300, deadline=None)
    @given(code=code_strategy)
    def test_single_role_user_denied_other_module(self, code: str):
        """R10.5: a single-role user is denied every code of the other module.

        For a designer-only user, every operational code is denied; for an
        operational-only user, every designer code is denied. Each is still
        granted its own module's codes.
        """
        module = permission_module(code)

        designer_user = _make_designer_user()
        operational_user = _make_operational_user()

        if module == "designer":
            _SVC.require(designer_user, code, study_id=STUDY)
            with pytest.raises(AuthorizationError):
                _SVC.require(operational_user, code, study_id=STUDY)
        elif module == "operational":
            _SVC.require(operational_user, code, study_id=STUDY)
            with pytest.raises(AuthorizationError):
                _SVC.require(designer_user, code, study_id=STUDY)
        else:
            # Shared code: neither single-module role grants it.
            with pytest.raises(AuthorizationError):
                _SVC.require(designer_user, code, study_id=STUDY)
            with pytest.raises(AuthorizationError):
                _SVC.require(operational_user, code, study_id=STUDY)

    @settings(max_examples=300, deadline=None)
    @given(
        designer_code=st.sampled_from(sorted(DESIGNER_PERMISSION_CODES)),
        operational_code=st.sampled_from(sorted(OPERATIONAL_PERMISSION_CODES)),
    )
    def test_both_role_user_satisfies_each_module_via_own_role(
        self,
        designer_code: str,
        operational_code: str,
    ):
        """R10.6: a both-role user is allowed designer AND operational codes.

        Crucially, each is authorized by its own role — the designer role never
        authorizes the operational code and vice versa. We verify this by
        confirming the designer code resolves only through a grant tagged with
        the designer module and the operational code only through an
        operational-tagged grant, while both are granted overall.
        """
        user = _make_both_role_user()

        # Both are granted overall.
        _SVC.require(user, designer_code, study_id=STUDY)
        _SVC.require(user, operational_code, study_id=STUDY)

        # Each code resolves only through a grant whose role owns that module —
        # no single grant spans both modules, so one role never cross-authorizes.
        scope = _SVC.resolve_scope(user)
        designer_grants = [
            g for g in scope.grants if g.permission_code == designer_code
        ]
        operational_grants = [
            g for g in scope.grants if g.permission_code == operational_code
        ]
        assert designer_grants, "both-role user must hold the designer grant"
        assert operational_grants, "both-role user must hold the operational grant"
        for grant in designer_grants:
            assert grant.role_modules == ("designer",)
        for grant in operational_grants:
            assert grant.role_modules == ("operational",)

    @settings(max_examples=200, deadline=None)
    @given(
        code=st.sampled_from(
            (
                *sorted(DESIGNER_PERMISSION_CODES),
                *sorted(OPERATIONAL_PERMISSION_CODES),
            )
        )
    )
    def test_default_deny_without_owning_role(self, code: str):
        """R10.4: a module-scoped code with no owning-role grant is denied.

        Two independent paths to "ownership cannot be confirmed" are exercised,
        and both default to deny:

          1. a user holding no role at all, and
          2. a user whose only role grants shared/platform codes (so its roles
             own neither module, and the module-scoped code is simply absent).
        """
        # No module role at all.
        with pytest.raises(AuthorizationError):
            _SVC.require(_make_neither_user(), code, study_id=STUDY)

        # A role granting only shared codes owns neither module, so a request
        # for a module-scoped code is denied by default.
        shared_only = _role_with("SharedOnly", ["user.list", "audit.read"])
        shared_user = StubUser(
            user_roles=[StubUserRole(role=shared_only, study_id=STUDY)]
        )
        with pytest.raises(AuthorizationError):
            _SVC.require(shared_user, code, study_id=STUDY)
