"""Tests for Permission_Service scope resolution and enforcement.

Validates Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 23.4
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

import pytest

from app.core.exceptions import AuthorizationError
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.permission_service import PermissionService

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
        """Site grant matches only its study+site."""
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(
                    permission_code="form.enter", study_id=STUDY_A, site_id=SITE_1
                )
            ]
        )
        assert scope.has_permission("form.enter", study_id=STUDY_A, site_id=SITE_1) is True
        assert scope.has_permission("form.enter", study_id=STUDY_A, site_id=SITE_2) is False

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
