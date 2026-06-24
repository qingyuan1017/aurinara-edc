"""Property-based test for scope-filtered listings.

**Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

Property 3: Listing and aggregation are scope-filtered.

Generates random users with random role assignments (system/study/site scope),
random lists of study IDs and site IDs, and asserts that:
  1. filter_studies() returns ONLY the study IDs within the user's scope
  2. filter_sites() returns ONLY the site IDs within the user's scope
  3. System-scope users always see all studies/sites
  4. Users with no roles see nothing
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.identity import Permission, Role, RolePermission, ScopeLevel, User, UserRole
from app.services.permission_service import PermissionService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

uuid_strategy = st.uuids()

# Generate a list of study UUIDs (the "universe" of studies)
study_ids_strategy = st.lists(uuid_strategy, min_size=0, max_size=10, unique=True)

# Generate a list of site UUIDs (the "universe" of sites)
site_ids_strategy = st.lists(uuid_strategy, min_size=0, max_size=10, unique=True)

# Scope levels for role assignments
scope_level_strategy = st.sampled_from([ScopeLevel.system, ScopeLevel.study, ScopeLevel.site])


def _make_permission(code: str) -> MagicMock:
    """Create a stub Permission object."""
    perm = MagicMock(spec=Permission)
    perm.code = code
    return perm


def _make_role_permission(code: str) -> MagicMock:
    """Create a stub RolePermission with an associated Permission."""
    rp = MagicMock(spec=RolePermission)
    rp.permission = _make_permission(code)
    return rp


def _make_role(scope_level: ScopeLevel, permission_codes: list[str]) -> MagicMock:
    """Create a stub Role with a given scope level and permission codes."""
    role = MagicMock(spec=Role)
    role.scope_level = scope_level
    role.role_permissions = [_make_role_permission(code) for code in permission_codes]
    return role


def _make_user_role(
    role: MagicMock,
    study_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a stub UserRole assignment with the given scope."""
    ur = MagicMock(spec=UserRole)
    ur.role = role
    ur.study_id = study_id
    ur.site_id = site_id
    return ur


def _make_user(user_roles: list[MagicMock]) -> MagicMock:
    """Create a stub User with given user_roles."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.user_roles = user_roles
    return user


@st.composite
def role_assignment_strategy(draw, available_study_ids: list[uuid.UUID], available_site_ids: list[uuid.UUID]):
    """Generate a single role assignment with a random scope level.

    - System scope: study_id=None, site_id=None
    - Study scope: study_id chosen from available studies, site_id=None
    - Site scope: study_id chosen from available studies, site_id chosen from available sites
    """
    scope = draw(scope_level_strategy)
    permission_code = draw(st.sampled_from(["study.read", "form.read", "subject.read", "query.read"]))

    if scope == ScopeLevel.system:
        return {
            "scope_level": scope,
            "permission_code": permission_code,
            "study_id": None,
            "site_id": None,
        }
    elif scope == ScopeLevel.study:
        # Need at least one study to assign study-scope
        if not available_study_ids:
            # Fall back to system scope
            return {
                "scope_level": ScopeLevel.system,
                "permission_code": permission_code,
                "study_id": None,
                "site_id": None,
            }
        study_id = draw(st.sampled_from(available_study_ids))
        return {
            "scope_level": scope,
            "permission_code": permission_code,
            "study_id": study_id,
            "site_id": None,
        }
    else:  # site scope
        # Need at least one study and one site
        if not available_study_ids or not available_site_ids:
            # Fall back to system scope
            return {
                "scope_level": ScopeLevel.system,
                "permission_code": permission_code,
                "study_id": None,
                "site_id": None,
            }
        study_id = draw(st.sampled_from(available_study_ids))
        site_id = draw(st.sampled_from(available_site_ids))
        return {
            "scope_level": scope,
            "permission_code": permission_code,
            "study_id": study_id,
            "site_id": site_id,
        }


@st.composite
def scope_filtering_scenario(draw):
    """Generate a complete scope-filtering scenario.

    Produces:
      - all_study_ids: the full universe of study IDs
      - all_site_ids: the full universe of site IDs
      - role_assignments: list of role assignment dicts for the user
    """
    all_study_ids = draw(study_ids_strategy)
    all_site_ids = draw(site_ids_strategy)

    # Number of role assignments (0 = no roles)
    num_assignments = draw(st.integers(min_value=0, max_value=5))

    role_assignments = []
    for _ in range(num_assignments):
        assignment = draw(role_assignment_strategy(all_study_ids, all_site_ids))
        role_assignments.append(assignment)

    return {
        "all_study_ids": all_study_ids,
        "all_site_ids": all_site_ids,
        "role_assignments": role_assignments,
    }


def _build_user_from_scenario(scenario: dict) -> MagicMock:
    """Build a stub User from a scenario's role_assignments."""
    user_roles = []
    for assignment in scenario["role_assignments"]:
        role = _make_role(assignment["scope_level"], [assignment["permission_code"]])
        ur = _make_user_role(
            role=role,
            study_id=assignment["study_id"],
            site_id=assignment["site_id"],
        )
        user_roles.append(ur)
    return _make_user(user_roles)


def _has_system_grant(scenario: dict) -> bool:
    """Check if any assignment is system-scope."""
    return any(
        a["study_id"] is None and a["site_id"] is None
        for a in scenario["role_assignments"]
    )


def _expected_study_ids(scenario: dict) -> set[uuid.UUID]:
    """Compute which study IDs the user should see given their assignments."""
    if _has_system_grant(scenario):
        return set(scenario["all_study_ids"])

    # Collect study IDs from study-scope and site-scope grants
    allowed = set()
    for assignment in scenario["role_assignments"]:
        if assignment["study_id"] is not None:
            allowed.add(assignment["study_id"])
    return allowed


def _expected_site_ids(scenario: dict) -> set[uuid.UUID]:
    """Compute which site IDs the user should see given their assignments."""
    if _has_system_grant(scenario):
        return set(scenario["all_site_ids"])

    # Collect site IDs from site-scope grants only
    allowed = set()
    for assignment in scenario["role_assignments"]:
        if assignment["site_id"] is not None:
            allowed.add(assignment["site_id"])
    return allowed


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestScopeFilteredListings:
    """Property-based tests for scope-filtered listings.

    **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**
    """

    @settings(max_examples=150, deadline=None)
    @given(scenario=scope_filtering_scenario())
    def test_filter_studies_returns_only_in_scope_studies(self, scenario):
        """filter_studies() returns ONLY the study IDs within the user's scope.

        **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

        For any user with any combination of role assignments:
        - System-scope users see all studies
        - Study/site-scope users see only their assigned study IDs
        - The result is always a subset of the input study_ids
        """
        service = PermissionService()
        user = _build_user_from_scenario(scenario)
        all_study_ids = scenario["all_study_ids"]

        result = service.filter_studies(user, all_study_ids)

        # Result must be a subset of the input
        assert set(result).issubset(set(all_study_ids)), (
            "filter_studies returned IDs not in the input list"
        )

        # Result must match expected
        expected = _expected_study_ids(scenario)
        # Intersect with what was actually passed in
        expected_in_input = expected.intersection(set(all_study_ids))
        assert set(result) == expected_in_input, (
            f"filter_studies mismatch: got {set(result)}, expected {expected_in_input}"
        )

    @settings(max_examples=150, deadline=None)
    @given(scenario=scope_filtering_scenario())
    def test_filter_sites_returns_only_in_scope_sites(self, scenario):
        """filter_sites() returns ONLY the site IDs within the user's scope.

        **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

        For any user with any combination of role assignments:
        - System-scope users see all sites
        - Site-scope users see only their assigned site IDs
        - The result is always a subset of the input site_ids
        """
        service = PermissionService()
        user = _build_user_from_scenario(scenario)
        all_site_ids = scenario["all_site_ids"]

        result = service.filter_sites(user, all_site_ids)

        # Result must be a subset of the input
        assert set(result).issubset(set(all_site_ids)), (
            "filter_sites returned IDs not in the input list"
        )

        # Result must match expected
        expected = _expected_site_ids(scenario)
        # Intersect with what was actually passed in
        expected_in_input = expected.intersection(set(all_site_ids))
        assert set(result) == expected_in_input, (
            f"filter_sites mismatch: got {set(result)}, expected {expected_in_input}"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        all_study_ids=study_ids_strategy,
        all_site_ids=site_ids_strategy,
    )
    def test_system_scope_users_see_everything(self, all_study_ids, all_site_ids):
        """System-scope users always see all studies and sites.

        **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

        A user with at least one system-scope role assignment must receive
        the full, unfiltered list of studies and sites.
        """
        service = PermissionService()

        # Create a user with a system-scope role
        role = _make_role(ScopeLevel.system, ["study.read"])
        ur = _make_user_role(role=role, study_id=None, site_id=None)
        user = _make_user([ur])

        filtered_studies = service.filter_studies(user, all_study_ids)
        filtered_sites = service.filter_sites(user, all_site_ids)

        assert set(filtered_studies) == set(all_study_ids), (
            "System-scope user must see ALL studies"
        )
        assert set(filtered_sites) == set(all_site_ids), (
            "System-scope user must see ALL sites"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        all_study_ids=study_ids_strategy,
        all_site_ids=site_ids_strategy,
    )
    def test_no_roles_user_sees_nothing(self, all_study_ids, all_site_ids):
        """Users with no roles see nothing.

        **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

        A user with zero role assignments must receive empty lists from both
        filter_studies and filter_sites.
        """
        service = PermissionService()

        # Create a user with no roles
        user = _make_user([])

        filtered_studies = service.filter_studies(user, all_study_ids)
        filtered_sites = service.filter_sites(user, all_site_ids)

        assert filtered_studies == [], (
            "User with no roles must see no studies"
        )
        assert filtered_sites == [], (
            "User with no roles must see no sites"
        )

    @settings(max_examples=150, deadline=None)
    @given(scenario=scope_filtering_scenario())
    def test_filtering_preserves_order(self, scenario):
        """filter_studies and filter_sites preserve the order of the input list.

        **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

        The filtered output must be a subsequence of the input (same relative order).
        """
        service = PermissionService()
        user = _build_user_from_scenario(scenario)

        all_study_ids = scenario["all_study_ids"]
        all_site_ids = scenario["all_site_ids"]

        filtered_studies = service.filter_studies(user, all_study_ids)
        filtered_sites = service.filter_sites(user, all_site_ids)

        # Check order preservation for studies
        study_indices = [all_study_ids.index(sid) for sid in filtered_studies]
        assert study_indices == sorted(study_indices), (
            "filter_studies must preserve input order"
        )

        # Check order preservation for sites
        site_indices = [all_site_ids.index(sid) for sid in filtered_sites]
        assert site_indices == sorted(site_indices), (
            "filter_sites must preserve input order"
        )
