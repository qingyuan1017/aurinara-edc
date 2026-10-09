"""Tests for Permission_Service scope resolution and enforcement.

Validates Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 23.4
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

import pytest

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import (
    CTMS_PERMISSION_CODES,
    DESIGNER_PERMISSION_CODES,
    OPERATIONAL_PERMISSION_CODES,
    ROLE_DEFINITIONS,
    permission_module,
    role_modules,
)
from app.schemas.shared.permission import AuthorizationScope, PermissionGrant
from app.services.shared.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Lightweight stubs for ORM objects (avoids database dependency in unit tests)
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


@dataclass
class StubObject:
    """Stub for a domain object with study/site scope."""

    study_id: UUID | None = None
    site_id: UUID | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STUDY_A = uuid.uuid4()
STUDY_B = uuid.uuid4()
SITE_1 = uuid.uuid4()
SITE_2 = uuid.uuid4()


def _make_system_admin() -> StubUser:
    """Create a user with system-scope admin role."""
    perms = [
        StubRolePermission(permission=StubPermission(code="user.list")),
        StubRolePermission(permission=StubPermission(code="study.create")),
        StubRolePermission(permission=StubPermission(code="audit.read")),
    ]
    role = StubRole(name="System Administrator", scope_level="system", role_permissions=perms)
    user_role = StubUserRole(role=role, study_id=None, site_id=None)
    return StubUser(user_roles=[user_role])


def _make_study_admin(study_id: UUID) -> StubUser:
    """Create a user with study-scope admin role for a given study."""
    perms = [
        StubRolePermission(permission=StubPermission(code="study.configure")),
        StubRolePermission(permission=StubPermission(code="form.configure")),
    ]
    role = StubRole(name="Study Administrator", scope_level="study", role_permissions=perms)
    user_role = StubUserRole(role=role, study_id=study_id, site_id=None)
    return StubUser(user_roles=[user_role])


def _make_site_coordinator(study_id: UUID, site_id: UUID) -> StubUser:
    """Create a user with site-scope coordinator role."""
    perms = [
        StubRolePermission(permission=StubPermission(code="subject.create")),
        StubRolePermission(permission=StubPermission(code="form.enter")),
        StubRolePermission(permission=StubPermission(code="form.submit")),
    ]
    role = StubRole(name="Site Coordinator", scope_level="site", role_permissions=perms)
    user_role = StubUserRole(role=role, study_id=study_id, site_id=site_id)
    return StubUser(user_roles=[user_role])


def _make_multi_role_user() -> StubUser:
    """Create a user with multiple role assignments at different scopes."""
    study_perms = [
        StubRolePermission(permission=StubPermission(code="query.create")),
        StubRolePermission(permission=StubPermission(code="audit.read")),
    ]
    study_role = StubRole(name="Data Manager", scope_level="study", role_permissions=study_perms)

    site_perms = [
        StubRolePermission(permission=StubPermission(code="form.enter")),
        StubRolePermission(permission=StubPermission(code="form.submit")),
    ]
    site_role = StubRole(name="Site Coordinator", scope_level="site", role_permissions=site_perms)

    return StubUser(
        user_roles=[
            StubUserRole(role=study_role, study_id=STUDY_A, site_id=None),
            StubUserRole(role=site_role, study_id=STUDY_B, site_id=SITE_2),
        ]
    )


@pytest.fixture
def svc() -> PermissionService:
    """Return a fresh PermissionService instance."""
    return PermissionService()


# ---------------------------------------------------------------------------
# Tests: resolve_scope (Requirement 2.1)
# ---------------------------------------------------------------------------


class TestResolveScope:
    """Tests for PermissionService.resolve_scope."""

    def test_system_scope_produces_none_study_site(self, svc: PermissionService):
        """System-scope roles produce grants with study_id=None, site_id=None."""
        user = _make_system_admin()
        scope = svc.resolve_scope(user)

        assert len(scope.grants) == 3
        for grant in scope.grants:
            assert grant.study_id is None
            assert grant.site_id is None

    def test_study_scope_produces_study_id(self, svc: PermissionService):
        """Study-scope roles produce grants tagged with the assignment's study_id."""
        user = _make_study_admin(STUDY_A)
        scope = svc.resolve_scope(user)

        assert len(scope.grants) == 2
        for grant in scope.grants:
            assert grant.study_id == STUDY_A
            assert grant.site_id is None

    def test_site_scope_produces_study_and_site(self, svc: PermissionService):
        """Site-scope roles produce grants tagged with both study_id and site_id."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        scope = svc.resolve_scope(user)

        assert len(scope.grants) == 3
        for grant in scope.grants:
            assert grant.study_id == STUDY_A
            assert grant.site_id == SITE_1

    def test_multi_role_union(self, svc: PermissionService):
        """Multiple role assignments produce the union of all grants."""
        user = _make_multi_role_user()
        scope = svc.resolve_scope(user)

        # 2 from data manager + 2 from site coordinator = 4
        assert len(scope.grants) == 4
        codes = {g.permission_code for g in scope.grants}
        assert codes == {"query.create", "audit.read", "form.enter", "form.submit"}

    def test_empty_roles_produces_empty_scope(self, svc: PermissionService):
        """A user with no roles gets an empty scope."""
        user = StubUser(user_roles=[])
        scope = svc.resolve_scope(user)

        assert scope.grants == []


# ---------------------------------------------------------------------------
# Tests: require (Requirements 2.2, 2.3, 23.4)
# ---------------------------------------------------------------------------


class TestRequire:
    """Tests for PermissionService.require."""

    def test_system_admin_passes_any_study(self, svc: PermissionService):
        """System-scope grants allow access regardless of target study/site."""
        user = _make_system_admin()
        # Should not raise
        svc.require(user, "study.create", study_id=STUDY_A)

    def test_system_admin_passes_no_scope(self, svc: PermissionService):
        """System-scope grants work even without a specific study/site."""
        user = _make_system_admin()
        svc.require(user, "user.list")

    def test_study_admin_passes_own_study(self, svc: PermissionService):
        """Study-scope grants allow access to their assigned study."""
        user = _make_study_admin(STUDY_A)
        svc.require(user, "study.configure", study_id=STUDY_A)

    def test_study_admin_denied_other_study(self, svc: PermissionService):
        """Study-scope grants deny access to a different study."""
        user = _make_study_admin(STUDY_A)
        with pytest.raises(AuthorizationError) as exc_info:
            svc.require(user, "study.configure", study_id=STUDY_B)
        assert exc_info.value.details["required_permission"] == "study.configure"

    def test_site_coordinator_passes_own_site(self, svc: PermissionService):
        """Site-scope grants allow access to their assigned study+site."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        svc.require(user, "form.enter", study_id=STUDY_A, site_id=SITE_1)

    def test_site_coordinator_denied_other_site(self, svc: PermissionService):
        """Site-scope grants deny access to a different site."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        with pytest.raises(AuthorizationError):
            svc.require(user, "form.enter", study_id=STUDY_A, site_id=SITE_2)

    def test_site_coordinator_denied_wrong_permission(self, svc: PermissionService):
        """Users are denied permissions they don't hold."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        with pytest.raises(AuthorizationError):
            svc.require(user, "audit.read", study_id=STUDY_A, site_id=SITE_1)

    def test_user_no_roles_denied(self, svc: PermissionService):
        """A user with no roles is always denied."""
        user = StubUser(user_roles=[])
        with pytest.raises(AuthorizationError):
            svc.require(user, "study.create")

    def test_inactive_user_is_rejected_before_scope_resolution(self, svc: PermissionService):
        """Deactivation invalidates new actions even when role grants remain attached."""
        user = _make_system_admin()
        user.status = "inactive"
        with pytest.raises(AuthenticationError, match="Account is inactive"):
            svc.require(user, "study.create")

    def test_study_scope_filters_sites_when_parent_studies_are_known(self, svc: PermissionService):
        """Study grants include mapped sites while site grants stay exact."""
        user = _make_study_admin(STUDY_A)
        site_studies = {SITE_1: STUDY_A, SITE_2: STUDY_B}
        assert svc.filter_sites(user, [SITE_1, SITE_2], site_studies) == [SITE_1]

    def test_removed_site_scope_denies_new_action(self, svc: PermissionService):
        """Removing the current assignment immediately removes authorization."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        user.user_roles.clear()
        with pytest.raises(AuthorizationError):
            svc.require(user, "form.enter", study_id=STUDY_A, site_id=SITE_1)

    def test_error_details_contain_permission_info(self, svc: PermissionService):
        """AuthorizationError details include the required permission and scope."""
        user = StubUser(user_roles=[])
        with pytest.raises(AuthorizationError) as exc_info:
            svc.require(user, "form.enter", study_id=STUDY_A, site_id=SITE_1)
        assert exc_info.value.details["required_permission"] == "form.enter"
        assert exc_info.value.details["study_id"] == str(STUDY_A)
        assert exc_info.value.details["site_id"] == str(SITE_1)


# ---------------------------------------------------------------------------
# Tests: filter_studies (Requirement 2.4)
# ---------------------------------------------------------------------------


class TestFilterStudies:
    """Tests for PermissionService.filter_studies."""

    def test_system_admin_sees_all(self, svc: PermissionService):
        """System-scope users see all studies."""
        user = _make_system_admin()
        result = svc.filter_studies(user, [STUDY_A, STUDY_B])
        assert set(result) == {STUDY_A, STUDY_B}

    def test_study_admin_sees_own_study(self, svc: PermissionService):
        """Study-scope users see only their assigned study."""
        user = _make_study_admin(STUDY_A)
        result = svc.filter_studies(user, [STUDY_A, STUDY_B])
        assert result == [STUDY_A]

    def test_site_coordinator_sees_study_of_site(self, svc: PermissionService):
        """Site-scope users see the study their site belongs to."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        result = svc.filter_studies(user, [STUDY_A, STUDY_B])
        assert result == [STUDY_A]

    def test_no_roles_sees_nothing(self, svc: PermissionService):
        """A user with no roles sees no studies."""
        user = StubUser(user_roles=[])
        result = svc.filter_studies(user, [STUDY_A, STUDY_B])
        assert result == []

    def test_preserves_order(self, svc: PermissionService):
        """Filtered results preserve the input order."""
        user = _make_multi_role_user()
        # Multi-role user has STUDY_A (data mgr) and STUDY_B (site coord)
        result = svc.filter_studies(user, [STUDY_B, STUDY_A])
        assert result == [STUDY_B, STUDY_A]


# ---------------------------------------------------------------------------
# Tests: filter_sites (Requirement 2.4)
# ---------------------------------------------------------------------------


class TestFilterSites:
    """Tests for PermissionService.filter_sites."""

    def test_system_admin_sees_all(self, svc: PermissionService):
        """System-scope users see all sites."""
        user = _make_system_admin()
        result = svc.filter_sites(user, [SITE_1, SITE_2])
        assert set(result) == {SITE_1, SITE_2}

    def test_site_coordinator_sees_own_site(self, svc: PermissionService):
        """Site-scope users see only their assigned site."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        result = svc.filter_sites(user, [SITE_1, SITE_2])
        assert result == [SITE_1]

    def test_no_roles_sees_nothing(self, svc: PermissionService):
        """A user with no roles sees no sites."""
        user = StubUser(user_roles=[])
        result = svc.filter_sites(user, [SITE_1, SITE_2])
        assert result == []


# ---------------------------------------------------------------------------
# Tests: assert_object_access (Requirement 2.5)
# ---------------------------------------------------------------------------


class TestAssertObjectAccess:
    """Tests for PermissionService.assert_object_access."""

    def test_system_admin_accesses_any_object(self, svc: PermissionService):
        """System-scope users can access any object."""
        user = _make_system_admin()
        obj = StubObject(study_id=STUDY_A, site_id=SITE_1)
        # Should not raise
        svc.assert_object_access(user, obj)

    def test_study_admin_accesses_own_study_object(self, svc: PermissionService):
        """Study-scope users can access objects in their study."""
        user = _make_study_admin(STUDY_A)
        obj = StubObject(study_id=STUDY_A, site_id=SITE_1)
        svc.assert_object_access(user, obj)

    def test_study_admin_denied_other_study_object(self, svc: PermissionService):
        """Study-scope users cannot access objects in another study."""
        user = _make_study_admin(STUDY_A)
        obj = StubObject(study_id=STUDY_B, site_id=SITE_1)
        with pytest.raises(AuthorizationError):
            svc.assert_object_access(user, obj)

    def test_site_coordinator_accesses_own_site_object(self, svc: PermissionService):
        """Site-scope users can access objects at their specific site."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        obj = StubObject(study_id=STUDY_A, site_id=SITE_1)
        svc.assert_object_access(user, obj)

    def test_site_coordinator_denied_other_site_object(self, svc: PermissionService):
        """Site-scope users cannot access objects at another site."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        obj = StubObject(study_id=STUDY_A, site_id=SITE_2)
        with pytest.raises(AuthorizationError):
            svc.assert_object_access(user, obj)

    def test_denied_object_without_study(self, svc: PermissionService):
        """Non-system users cannot access objects without study scope."""
        user = _make_study_admin(STUDY_A)
        obj = StubObject(study_id=None, site_id=None)
        with pytest.raises(AuthorizationError):
            svc.assert_object_access(user, obj)

    def test_multi_role_user_accesses_both_scopes(self, svc: PermissionService):
        """Multi-role users can access objects covered by any of their grants."""
        user = _make_multi_role_user()
        # Data manager for STUDY_A
        obj_a = StubObject(study_id=STUDY_A, site_id=None)
        svc.assert_object_access(user, obj_a)
        # Site coordinator for STUDY_B/SITE_2
        obj_b = StubObject(study_id=STUDY_B, site_id=SITE_2)
        svc.assert_object_access(user, obj_b)

    def test_multi_role_user_denied_uncovered_site(self, svc: PermissionService):
        """Multi-role users are denied access to objects outside all their grants."""
        user = _make_multi_role_user()
        # User has STUDY_B only at SITE_2, not SITE_1
        obj = StubObject(study_id=STUDY_B, site_id=SITE_1)
        with pytest.raises(AuthorizationError):
            svc.assert_object_access(user, obj)


# ---------------------------------------------------------------------------
# Tests: AuthorizationScope model
# ---------------------------------------------------------------------------


class TestAuthorizationScope:
    """Tests for the AuthorizationScope Pydantic model."""

    def test_has_permission_system_grant(self):
        """System grant matches any study/site."""
        scope = AuthorizationScope(
            grants=[PermissionGrant(permission_code="study.create")]
        )
        assert scope.has_permission("study.create", study_id=STUDY_A) is True
        assert scope.has_permission("study.create") is True

    def test_has_permission_study_grant(self):
        """Study grant matches only its study."""
        scope = AuthorizationScope(
            grants=[PermissionGrant(permission_code="form.configure", study_id=STUDY_A)]
        )
        assert scope.has_permission("form.configure", study_id=STUDY_A) is True
        assert scope.has_permission("form.configure", study_id=STUDY_B) is False

    def test_has_permission_site_grant(self):
        """Site grant matches only its study+site.

        ``form.enter`` is an operational-module code, so the grant must carry
        operational module ownership to satisfy the module gate (Requirement 10).
        """
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(
                    permission_code="form.enter",
                    study_id=STUDY_A,
                    site_id=SITE_1,
                    role_modules=("operational",),
                )
            ]
        )
        assert scope.has_permission("form.enter", study_id=STUDY_A, site_id=SITE_1) is True
        assert scope.has_permission("form.enter", study_id=STUDY_A, site_id=SITE_2) is False

    def test_module_gate_denies_grant_without_role_module(self):
        """A module-scoped code with no role-module ownership is denied (default-deny)."""
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(
                    permission_code="form.enter", study_id=STUDY_A, site_id=SITE_1
                )
            ]
        )
        assert (
            scope.has_permission("form.enter", study_id=STUDY_A, site_id=SITE_1) is False
        )

    def test_has_system_grant_true(self):
        """has_system_grant returns True for system-scope grants."""
        scope = AuthorizationScope(
            grants=[PermissionGrant(permission_code="user.list")]
        )
        assert scope.has_system_grant() is True
        assert scope.has_system_grant("user.list") is True
        assert scope.has_system_grant("form.enter") is False

    def test_has_system_grant_false(self):
        """has_system_grant returns False when no system grants exist."""
        scope = AuthorizationScope(
            grants=[PermissionGrant(permission_code="form.enter", study_id=STUDY_A)]
        )
        assert scope.has_system_grant() is False

    def test_get_study_ids(self):
        """get_study_ids returns all unique study IDs from grants."""
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(permission_code="form.enter", study_id=STUDY_A, site_id=SITE_1),
                PermissionGrant(permission_code="audit.read", study_id=STUDY_B),
                PermissionGrant(permission_code="user.list"),  # system scope
            ]
        )
        assert scope.get_study_ids() == {STUDY_A, STUDY_B}

    def test_get_site_ids(self):
        """get_site_ids returns all unique site IDs from grants."""
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(permission_code="form.enter", study_id=STUDY_A, site_id=SITE_1),
                PermissionGrant(permission_code="form.submit", study_id=STUDY_A, site_id=SITE_2),
                PermissionGrant(permission_code="audit.read", study_id=STUDY_B),
            ]
        )
        assert scope.get_site_ids() == {SITE_1, SITE_2}

    def test_ctms_requirement_alias_matches_canonical_permission(self):
        """CTMS route terminology resolves to the stored shared code."""
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(
                    permission_code="ctms.operational_study_management",
                    study_id=STUDY_A,
                )
            ]
        )
        assert scope.has_permission(
            "operational-study-management", study_id=STUDY_A
        ) is True


class TestCTMSRoleDefinitions:
    """CTMS built-in roles expose the required read/write boundaries."""

    def test_ctms_roles_are_seeded_with_expected_scopes(self):
        assert ROLE_DEFINITIONS["CTMS_Admin"]["scope"] == "system"
        assert ROLE_DEFINITIONS["CTMS_Operations_User"]["scope"] == "study"
        assert ROLE_DEFINITIONS["CTMS_Viewer"]["scope"] == "study"

    def test_viewer_has_only_read_permission(self):
        viewer_permissions = set(ROLE_DEFINITIONS["CTMS_Viewer"]["permissions"])
        assert viewer_permissions == {"ctms.operational_data_read"}
        assert not viewer_permissions & (CTMS_PERMISSION_CODES - viewer_permissions)

    def test_admin_contains_all_ctms_permissions(self):
        admin_permissions = set(ROLE_DEFINITIONS["CTMS_Admin"]["permissions"])
        assert admin_permissions >= CTMS_PERMISSION_CODES


# ---------------------------------------------------------------------------
# Tests: module-scoped separation of duties (Requirement 10)
# ---------------------------------------------------------------------------
#
# Validates Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
#
# A designer-module permission is effective only through a Designer_Role; an
# operational-module permission only through an Operational_Role. Authorization
# is evaluated server-side and defaults to deny. A single-role user is confined
# to that one module; a both-role user has each permission set enforced only
# within its own module scope.

# A representative permission from each module used across the tests below.
DESIGNER_PERM = "designer.form.configure"
OPERATIONAL_PERM = "form.enter"


def _role_with(name: str, scope: str, codes: list[str]) -> StubRole:
    """Build a StubRole granting the given permission codes."""
    perms = [StubRolePermission(permission=StubPermission(code=c)) for c in codes]
    return StubRole(name=name, scope_level=scope, role_permissions=perms)


def _make_designer_user(study_id: UUID = STUDY_A) -> StubUser:
    """User holding only a Designer_Role scoped to a study."""
    role = _role_with(
        "Designer_Role", "study", sorted(DESIGNER_PERMISSION_CODES)
    )
    return StubUser(user_roles=[StubUserRole(role=role, study_id=study_id, site_id=None)])


def _make_operational_user(study_id: UUID = STUDY_A) -> StubUser:
    """User holding only an Operational_Role scoped to a study."""
    role = _role_with(
        "Operational_Role", "study", sorted(OPERATIONAL_PERMISSION_CODES)
    )
    return StubUser(user_roles=[StubUserRole(role=role, study_id=study_id, site_id=None)])


def _make_both_role_user(study_id: UUID = STUDY_A) -> StubUser:
    """User holding both a Designer_Role and an Operational_Role on one study."""
    designer_role = _role_with(
        "Designer_Role", "study", sorted(DESIGNER_PERMISSION_CODES)
    )
    operational_role = _role_with(
        "Operational_Role", "study", sorted(OPERATIONAL_PERMISSION_CODES)
    )
    return StubUser(
        user_roles=[
            StubUserRole(role=designer_role, study_id=study_id, site_id=None),
            StubUserRole(role=operational_role, study_id=study_id, site_id=None),
        ]
    )


class TestPermissionModuleClassification:
    """The static module classification is cohesive and non-overlapping."""

    def test_designer_and_operational_sets_are_disjoint(self):
        """A code never belongs to both modules."""
        assert not (DESIGNER_PERMISSION_CODES & OPERATIONAL_PERMISSION_CODES)

    def test_permission_module_classifies_designer(self):
        for code in DESIGNER_PERMISSION_CODES:
            assert permission_module(code) == "designer"

    def test_permission_module_classifies_operational(self):
        for code in OPERATIONAL_PERMISSION_CODES:
            assert permission_module(code) == "operational"

    def test_shared_codes_are_exempt(self):
        """Shared/platform codes return None and are not module-gated."""
        for code in ("user.list", "audit.read", "ctms.operational_data_read"):
            assert permission_module(code) is None

    def test_role_modules_single_and_both(self):
        assert role_modules(DESIGNER_PERMISSION_CODES) == ("designer",)
        assert role_modules(OPERATIONAL_PERMISSION_CODES) == ("operational",)
        both = role_modules(DESIGNER_PERMISSION_CODES | OPERATIONAL_PERMISSION_CODES)
        assert set(both) == {"designer", "operational"}
        assert role_modules({"user.list", "audit.read"}) == ()


class TestModuleScopedRoleSeeding:
    """Designer_Role and Operational_Role are seeded with the right codes (R10.1)."""

    def test_designer_role_holds_only_designer_codes(self):
        perms = set(ROLE_DEFINITIONS["Designer_Role"]["permissions"])
        assert perms == set(DESIGNER_PERMISSION_CODES)
        assert not (perms & OPERATIONAL_PERMISSION_CODES)

    def test_operational_role_holds_only_operational_codes(self):
        perms = set(ROLE_DEFINITIONS["Operational_Role"]["permissions"])
        assert perms == set(OPERATIONAL_PERMISSION_CODES)
        assert not (perms & DESIGNER_PERMISSION_CODES)


class TestDesignerPermissionRequiresDesignerRole:
    """A designer permission is grantable/effective only through a Designer_Role."""

    def test_designer_role_grants_designer_permission(self, svc: PermissionService):
        user = _make_designer_user(STUDY_A)
        svc.require(user, DESIGNER_PERM, study_id=STUDY_A)

    def test_operational_role_cannot_grant_designer_permission(self, svc: PermissionService):
        """An operational-only user is denied every designer permission (R10.2, R10.5)."""
        user = _make_operational_user(STUDY_A)
        for code in DESIGNER_PERMISSION_CODES:
            with pytest.raises(AuthorizationError):
                svc.require(user, code, study_id=STUDY_A)

    def test_module_ownership_is_derived_from_codes_not_role_name(
        self, svc: PermissionService
    ):
        """Module ownership follows the codes a role grants, not its name.

        A role granting only operational codes owns only the operational module
        regardless of its name, so it cannot authorize any designer permission.
        """
        role = _role_with("Misnamed Designer_Role", "study", [OPERATIONAL_PERM])
        user = StubUser(
            user_roles=[StubUserRole(role=role, study_id=STUDY_A, site_id=None)]
        )
        svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)
        with pytest.raises(AuthorizationError):
            svc.require(user, DESIGNER_PERM, study_id=STUDY_A)


class TestOperationalPermissionRequiresOperationalRole:
    """An operational permission is grantable/effective only through an Operational_Role."""

    def test_operational_role_grants_operational_permission(self, svc: PermissionService):
        user = _make_operational_user(STUDY_A)
        svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)

    def test_designer_role_cannot_grant_operational_permission(self, svc: PermissionService):
        """A designer-only user is denied every operational permission (R10.3, R10.5)."""
        user = _make_designer_user(STUDY_A)
        for code in OPERATIONAL_PERMISSION_CODES:
            with pytest.raises(AuthorizationError):
                svc.require(user, code, study_id=STUDY_A)


class TestDefaultDeny:
    """Authorization defaults to deny when it cannot be confirmed (R10.4)."""

    def test_user_without_module_role_denied_designer(self, svc: PermissionService):
        """A user with no module role is denied a designer permission."""
        user = StubUser(user_roles=[])
        with pytest.raises(AuthorizationError):
            svc.require(user, DESIGNER_PERM, study_id=STUDY_A)

    def test_user_without_module_role_denied_operational(self, svc: PermissionService):
        """A user with no module role is denied an operational permission."""
        user = StubUser(user_roles=[])
        with pytest.raises(AuthorizationError):
            svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)

    def test_shared_role_does_not_satisfy_module_permission(self, svc: PermissionService):
        """A role holding only shared codes cannot satisfy a module permission."""
        role = _role_with("Shared", "study", ["audit.read", "user.list"])
        user = StubUser(
            user_roles=[StubUserRole(role=role, study_id=STUDY_A, site_id=None)]
        )
        with pytest.raises(AuthorizationError):
            svc.require(user, DESIGNER_PERM, study_id=STUDY_A)
        with pytest.raises(AuthorizationError):
            svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)

    def test_scope_mismatch_still_denies_module_permission(self, svc: PermissionService):
        """A designer role on another study does not authorize this study (R10.4)."""
        user = _make_designer_user(STUDY_A)
        with pytest.raises(AuthorizationError):
            svc.require(user, DESIGNER_PERM, study_id=STUDY_B)


class TestSingleRoleModuleIsolation:
    """A single-role user is confined to that one module (R10.5)."""

    def test_designer_only_user_isolated(self, svc: PermissionService):
        user = _make_designer_user(STUDY_A)
        # Allowed in its own module.
        svc.require(user, DESIGNER_PERM, study_id=STUDY_A)
        # Denied all operational-module permissions.
        with pytest.raises(AuthorizationError):
            svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)

    def test_operational_only_user_isolated(self, svc: PermissionService):
        user = _make_operational_user(STUDY_A)
        svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)
        with pytest.raises(AuthorizationError):
            svc.require(user, DESIGNER_PERM, study_id=STUDY_A)


class TestBothRoleModuleIsolation:
    """A both-role user has each set enforced only within its own module (R10.6)."""

    def test_both_roles_each_scoped_to_own_module(self, svc: PermissionService):
        user = _make_both_role_user(STUDY_A)
        # Each role authorizes its own module.
        svc.require(user, DESIGNER_PERM, study_id=STUDY_A)
        svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)

    def test_both_roles_do_not_cross_authorize(self, svc: PermissionService):
        """Neither role's grants leak into the other module's codes.

        Build a both-role user whose designer role is scoped to STUDY_A and
        operational role to STUDY_B. A designer permission must only resolve on
        STUDY_A, and an operational permission only on STUDY_B — one role never
        authorizes an action in the other module/scope."""
        designer_role = _role_with(
            "Designer_Role", "study", sorted(DESIGNER_PERMISSION_CODES)
        )
        operational_role = _role_with(
            "Operational_Role", "study", sorted(OPERATIONAL_PERMISSION_CODES)
        )
        user = StubUser(
            user_roles=[
                StubUserRole(role=designer_role, study_id=STUDY_A, site_id=None),
                StubUserRole(role=operational_role, study_id=STUDY_B, site_id=None),
            ]
        )
        # Designer permission resolves only on STUDY_A.
        svc.require(user, DESIGNER_PERM, study_id=STUDY_A)
        with pytest.raises(AuthorizationError):
            svc.require(user, DESIGNER_PERM, study_id=STUDY_B)
        # Operational permission resolves only on STUDY_B.
        svc.require(user, OPERATIONAL_PERM, study_id=STUDY_B)
        with pytest.raises(AuthorizationError):
            svc.require(user, OPERATIONAL_PERM, study_id=STUDY_A)

    def test_both_role_grants_carry_distinct_module_ownership(self, svc: PermissionService):
        """resolve_scope tags designer grants designer-owned and operational
        grants operational-owned, so no single grant spans both modules."""
        user = _make_both_role_user(STUDY_A)
        scope = svc.resolve_scope(user)
        for grant in scope.grants:
            module = permission_module(grant.permission_code)
            if module == "designer":
                assert grant.role_modules == ("designer",)
            elif module == "operational":
                assert grant.role_modules == ("operational",)
