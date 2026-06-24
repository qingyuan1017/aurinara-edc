"""Property-based test for authorization scope resolution.

**Validates: Requirements 2.1**

Property 1: Authorization scope is the union of role grants.

Generates random users with N roles (0..5), each role having M permissions (0..10),
each assigned at random study/site scopes (system, study, or site level). Verifies
that resolve_scope() returns grants that are exactly the union of all permission codes
from all assigned roles, each tagged with the correct study_id/site_id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Lightweight stubs (same pattern as test_permission_service.py)
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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Permission codes drawn from realistic EDC domain codes
PERMISSION_CODES = [
    "user.list",
    "user.create",
    "user.assign",
    "role.create",
    "role.delete",
    "study.create",
    "study.configure",
    "site.manage",
    "subject.create",
    "subject.read",
    "subject.update",
    "form.configure",
    "form.enter",
    "form.submit",
    "form.read",
    "query.create",
    "query.close",
    "query.respond",
    "audit.read",
    "data.export",
    "sdv.manage",
    "review.manage",
    "lock.manage",
    "signature.sign",
    "file.upload",
    "editcheck.configure",
    "version.publish",
]

permission_code_strategy = st.sampled_from(PERMISSION_CODES)


@st.composite
def scope_assignment_strategy(draw):
    """Generate a random scope assignment (system, study, or site level).

    Returns (scope_level, study_id, site_id) tuple.
    """
    scope_level = draw(st.sampled_from(["system", "study", "site"]))
    if scope_level == "system":
        return scope_level, None, None
    elif scope_level == "study":
        study_id = draw(st.uuids())
        return scope_level, study_id, None
    else:  # site
        study_id = draw(st.uuids())
        site_id = draw(st.uuids())
        return scope_level, study_id, site_id


@st.composite
def role_strategy(draw):
    """Generate a random role with 0..10 permissions at a random scope."""
    scope_level, study_id, site_id = draw(scope_assignment_strategy())

    # Generate 0..10 permission codes for this role (may contain duplicates within
    # a role, but each becomes a separate RolePermission entry)
    num_permissions = draw(st.integers(min_value=0, max_value=10))
    permission_codes = draw(
        st.lists(permission_code_strategy, min_size=num_permissions, max_size=num_permissions)
    )

    role_permissions = [
        StubRolePermission(permission=StubPermission(code=code)) for code in permission_codes
    ]
    role = StubRole(
        name=f"Role_{draw(st.uuids())}",
        scope_level=scope_level,
        role_permissions=role_permissions,
    )
    user_role = StubUserRole(role=role, study_id=study_id, site_id=site_id)
    return user_role, permission_codes, study_id, site_id


@st.composite
def user_with_roles_strategy(draw):
    """Generate a random user with 0..5 roles.

    Returns (user, expected_grants) where expected_grants is a list of
    (permission_code, study_id, site_id) tuples representing the expected output.
    """
    num_roles = draw(st.integers(min_value=0, max_value=5))
    roles_data = draw(st.lists(role_strategy(), min_size=num_roles, max_size=num_roles))

    user_roles = []
    expected_grants: list[tuple[str, UUID | None, UUID | None]] = []

    for user_role, permission_codes, study_id, site_id in roles_data:
        user_roles.append(user_role)
        for code in permission_codes:
            expected_grants.append((code, study_id, site_id))

    user = StubUser(user_roles=user_roles)
    return user, expected_grants


# ---------------------------------------------------------------------------
# Property 1: Authorization scope is the union of role grants
# ---------------------------------------------------------------------------


class TestScopeResolutionProperty:
    """Property-based tests for scope resolution.

    **Validates: Requirements 2.1**
    """

    @settings(max_examples=100, deadline=None)
    @given(data=user_with_roles_strategy())
    def test_scope_is_union_of_role_grants(self, data):
        """resolve_scope() returns grants that are exactly the union of all
        permission codes from all assigned roles, each tagged with the correct
        study_id/site_id.

        **Validates: Requirements 2.1**

        Asserts:
        1. Grants are exactly the union of all permission codes from all assigned roles
        2. Each grant is tagged with the correct study_id/site_id
        3. The number of grants equals the total sum of permissions across all roles
        4. Each grant's permission_code exists in the expected role's permissions
        """
        user, expected_grants = data
        svc = PermissionService()

        scope = svc.resolve_scope(user)

        # Assertion 3: grant count equals total permission count across all roles
        assert len(scope.grants) == len(expected_grants), (
            f"Expected {len(expected_grants)} grants but got {len(scope.grants)}. "
            f"The number of grants must equal the total sum of permissions across all roles."
        )

        # Convert actual grants to comparable tuples
        actual_grant_tuples = [
            (g.permission_code, g.study_id, g.site_id) for g in scope.grants
        ]

        # Assertion 1 & 2: grants are exactly the union of expected, each with correct scope
        # Sort both for comparison since order is not guaranteed
        assert sorted(actual_grant_tuples, key=str) == sorted(expected_grants, key=str), (
            "resolve_scope() must return exactly the union of all permission codes "
            "from all assigned roles, each tagged with the correct study_id/site_id."
        )

        # Assertion 4: each grant's permission_code exists in the expected role's permissions
        for grant in scope.grants:
            matching = [
                (code, sid, siteid)
                for code, sid, siteid in expected_grants
                if code == grant.permission_code
                and sid == grant.study_id
                and siteid == grant.site_id
            ]
            assert len(matching) > 0, (
                f"Grant ({grant.permission_code}, study={grant.study_id}, site={grant.site_id}) "
                f"does not correspond to any expected role permission."
            )

    @settings(max_examples=100, deadline=None)
    @given(data=user_with_roles_strategy())
    def test_system_scope_grants_have_null_ids(self, data):
        """System-scope role assignments produce grants with study_id=None, site_id=None.

        **Validates: Requirements 2.1**
        """
        user, expected_grants = data
        svc = PermissionService()

        scope = svc.resolve_scope(user)

        # For each system-scope role assignment, verify grants have null IDs
        for user_role in user.user_roles:
            if user_role.study_id is None and user_role.site_id is None:
                # This is a system-scope assignment
                for rp in user_role.role.role_permissions:
                    # Find corresponding grant(s)
                    matching_grants = [
                        g
                        for g in scope.grants
                        if g.permission_code == rp.permission.code
                        and g.study_id is None
                        and g.site_id is None
                    ]
                    assert len(matching_grants) >= 1, (
                        f"System-scope permission {rp.permission.code} "
                        f"must produce a grant with study_id=None, site_id=None."
                    )

    @settings(max_examples=100, deadline=None)
    @given(data=user_with_roles_strategy())
    def test_study_scope_grants_have_correct_study_id(self, data):
        """Study-scope role assignments produce grants tagged with the assignment's study_id.

        **Validates: Requirements 2.1**
        """
        user, expected_grants = data
        svc = PermissionService()

        scope = svc.resolve_scope(user)

        # For each study-scope role assignment, verify grants carry the study_id
        for user_role in user.user_roles:
            if user_role.study_id is not None and user_role.site_id is None:
                # This is a study-scope assignment
                for rp in user_role.role.role_permissions:
                    matching_grants = [
                        g
                        for g in scope.grants
                        if g.permission_code == rp.permission.code
                        and g.study_id == user_role.study_id
                        and g.site_id is None
                    ]
                    assert len(matching_grants) >= 1, (
                        f"Study-scope permission {rp.permission.code} for study "
                        f"{user_role.study_id} must produce a grant with that study_id."
                    )

    @settings(max_examples=100, deadline=None)
    @given(data=user_with_roles_strategy())
    def test_site_scope_grants_have_correct_study_and_site_id(self, data):
        """Site-scope role assignments produce grants tagged with both study_id and site_id.

        **Validates: Requirements 2.1**
        """
        user, expected_grants = data
        svc = PermissionService()

        scope = svc.resolve_scope(user)

        # For each site-scope role assignment, verify grants carry both IDs
        for user_role in user.user_roles:
            if user_role.study_id is not None and user_role.site_id is not None:
                # This is a site-scope assignment
                for rp in user_role.role.role_permissions:
                    matching_grants = [
                        g
                        for g in scope.grants
                        if g.permission_code == rp.permission.code
                        and g.study_id == user_role.study_id
                        and g.site_id == user_role.site_id
                    ]
                    assert len(matching_grants) >= 1, (
                        f"Site-scope permission {rp.permission.code} for study "
                        f"{user_role.study_id}/site {user_role.site_id} "
                        f"must produce a grant with those IDs."
                    )
