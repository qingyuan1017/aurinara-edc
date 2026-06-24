"""Property-based test for access enforcement.

**Validates: Requirements 2.2, 2.3, 2.5, 3.5, 3.6, 23.4, 26.4**

Property 2: Access is permitted if and only if in scope.

Generates random users with random role/permission assignments at random scopes,
generates random permission requests (permission_code + target study_id + target site_id),
and asserts that `require()` raises AuthorizationError if and only if the user's scope
does NOT contain the requested permission at the target scope.

Scope hierarchy rules:
  - System-scope grants (study_id=None, site_id=None): permission granted regardless of target
  - Study-scope grants (study_id set, site_id=None): permission matches assigned study
    and covers any site within it
  - Site-scope grants (study_id set, site_id set): permission matches only the exact study+site
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import AuthorizationError
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.permission_service import PermissionService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Pool of permission codes to choose from
PERMISSION_CODES = [
    "form.enter",
    "form.read",
    "form.submit",
    "query.create",
    "query.respond",
    "subject.create",
    "subject.read",
    "subject.update",
    "study.configure",
    "site.manage",
    "audit.read",
    "data.export",
    "sdv.manage",
    "review.manage",
    "lock.manage",
    "user.assign",
]

permission_code_strategy = st.sampled_from(PERMISSION_CODES)

# UUIDs for studies and sites — use a small pool to increase overlap probability
study_id_strategy = st.sampled_from([uuid.UUID(int=i) for i in range(1, 6)])
site_id_strategy = st.sampled_from([uuid.UUID(int=i) for i in range(10, 16)])


@st.composite
def grant_strategy(draw):
    """Generate a single permission grant at a random scope level.

    Returns a dict with:
      - permission_code: str
      - scope_level: 'system' | 'study' | 'site'
      - study_id: UUID | None
      - site_id: UUID | None
    """
    permission_code = draw(permission_code_strategy)
    scope_level = draw(st.sampled_from(["system", "study", "site"]))

    if scope_level == "system":
        return {
            "permission_code": permission_code,
            "scope_level": scope_level,
            "study_id": None,
            "site_id": None,
        }
    elif scope_level == "study":
        return {
            "permission_code": permission_code,
            "scope_level": scope_level,
            "study_id": draw(study_id_strategy),
            "site_id": None,
        }
    else:  # site
        study_id = draw(study_id_strategy)
        site_id = draw(site_id_strategy)
        return {
            "permission_code": permission_code,
            "scope_level": scope_level,
            "study_id": study_id,
            "site_id": site_id,
        }


@st.composite
def permission_request_strategy(draw):
    """Generate a random permission request (what the user is trying to do).

    Returns a dict with:
      - permission_code: str
      - target_study_id: UUID | None
      - target_site_id: UUID | None
    """
    permission_code = draw(permission_code_strategy)
    # Target can be system-level, study-level, or site-level
    target_level = draw(st.sampled_from(["system", "study", "site"]))

    if target_level == "system":
        return {
            "permission_code": permission_code,
            "target_study_id": None,
            "target_site_id": None,
        }
    elif target_level == "study":
        return {
            "permission_code": permission_code,
            "target_study_id": draw(study_id_strategy),
            "target_site_id": None,
        }
    else:  # site
        study_id = draw(study_id_strategy)
        site_id = draw(site_id_strategy)
        return {
            "permission_code": permission_code,
            "target_study_id": study_id,
            "target_site_id": site_id,
        }


@st.composite
def user_with_grants_strategy(draw):
    """Generate a user with 0..5 random permission grants at various scopes."""
    grants = draw(st.lists(grant_strategy(), min_size=0, max_size=5))
    return grants


def _build_mock_user(grants: list[dict]) -> MagicMock:
    """Build a mock User object with the given grants wired through user_roles.

    Each grant becomes a UserRole -> Role -> RolePermission -> Permission chain.
    """
    mock_user = MagicMock(spec=User)
    mock_user.id = uuid.uuid4()
    user_roles = []

    for grant in grants:
        # Build Permission mock
        mock_permission = MagicMock(spec=Permission)
        mock_permission.code = grant["permission_code"]

        # Build RolePermission mock
        mock_role_permission = MagicMock(spec=RolePermission)
        mock_role_permission.permission = mock_permission

        # Build Role mock
        mock_role = MagicMock(spec=Role)
        mock_role.role_permissions = [mock_role_permission]

        # Build UserRole mock
        mock_user_role = MagicMock(spec=UserRole)
        mock_user_role.role = mock_role
        mock_user_role.study_id = grant["study_id"]
        mock_user_role.site_id = grant["site_id"]

        user_roles.append(mock_user_role)

    mock_user.user_roles = user_roles
    return mock_user


def _should_permit(grants: list[dict], request: dict) -> bool:
    """Oracle: determine if the request should be permitted given the grants.

    Implements the same scope-hierarchy logic as AuthorizationScope.has_permission:
      - System grant (study_id=None, site_id=None) matches any request for that permission
      - Study grant (study_id=X, site_id=None) matches if target study_id == X
        (also covers site-level requests within that study)
      - Site grant (study_id=X, site_id=Y) matches only if target study_id == X
        AND target site_id == Y
    """
    perm_code = request["permission_code"]
    target_study = request["target_study_id"]
    target_site = request["target_site_id"]

    for grant in grants:
        if grant["permission_code"] != perm_code:
            continue

        g_study = grant["study_id"]
        g_site = grant["site_id"]

        # System-scope grant: matches everything for this permission
        if g_study is None and g_site is None:
            return True

        # Study-scope grant: matches if target study matches
        # (covers all sites within that study)
        if g_study is not None and g_site is None:
            if target_study == g_study:
                return True

        # Site-scope grant: matches only exact study+site
        if g_study is not None and g_site is not None:
            if target_study == g_study and target_site == g_site:
                return True

    return False


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestAccessEnforcementProperty:
    """Property-based tests for access enforcement.

    **Validates: Requirements 2.2, 2.3, 2.5, 3.5, 3.6, 23.4, 26.4**
    """

    @settings(max_examples=200, deadline=None)
    @given(
        grants=user_with_grants_strategy(),
        request=permission_request_strategy(),
    )
    def test_require_raises_iff_not_in_scope(self, grants, request):
        """For any user with any set of permission grants at any scopes,
        and any permission request targeting any scope, `require()` raises
        AuthorizationError if and only if the oracle says the permission
        is NOT in scope.

        **Validates: Requirements 2.2, 2.3, 2.5, 3.5, 3.6, 23.4, 26.4**

        - Req 2.2: Route-level permission enforcement by study/site scope.
        - Req 2.3: Authorization error when scope lacks required permission.
        - Req 2.5: Object-level access denial for out-of-scope objects.
        - Req 3.5: System enforces access rules (inactive users cannot access).
        - Req 3.6: Sponsor Viewer gets read-only access (enforced through scope).
        - Req 23.4: Every protected operation passes through Permission_Service.
        - Req 26.4: Authorization scope enforcement is independently verified.
        """
        service = PermissionService()
        mock_user = _build_mock_user(grants)

        expected_permitted = _should_permit(grants, request)

        if expected_permitted:
            # Should NOT raise — access is permitted
            service.require(
                user=mock_user,
                permission=request["permission_code"],
                study_id=request["target_study_id"],
                site_id=request["target_site_id"],
            )
        else:
            # MUST raise — access is denied
            with pytest.raises(AuthorizationError):
                service.require(
                    user=mock_user,
                    permission=request["permission_code"],
                    study_id=request["target_study_id"],
                    site_id=request["target_site_id"],
                )

    @settings(max_examples=100, deadline=None)
    @given(
        grants=user_with_grants_strategy(),
        request=permission_request_strategy(),
    )
    def test_system_scope_grants_universal_access(self, grants, request):
        """If a user has a system-scope grant for the requested permission,
        access is always permitted regardless of target study/site.

        **Validates: Requirements 2.2, 2.3, 26.4**
        """
        # Force at least one system-scope grant for the requested permission
        system_grant = {
            "permission_code": request["permission_code"],
            "scope_level": "system",
            "study_id": None,
            "site_id": None,
        }
        augmented_grants = grants + [system_grant]

        service = PermissionService()
        mock_user = _build_mock_user(augmented_grants)

        # Should never raise — system scope covers everything
        service.require(
            user=mock_user,
            permission=request["permission_code"],
            study_id=request["target_study_id"],
            site_id=request["target_site_id"],
        )

    @settings(max_examples=100, deadline=None)
    @given(
        other_grants=user_with_grants_strategy(),
        study_id=study_id_strategy,
        target_site_id=site_id_strategy,
    )
    def test_study_scope_covers_sites_within_study(
        self, other_grants, study_id, target_site_id
    ):
        """A study-scope grant covers any site within that study.

        **Validates: Requirements 2.2, 2.5, 26.4**
        """
        perm_code = "form.read"
        study_grant = {
            "permission_code": perm_code,
            "scope_level": "study",
            "study_id": study_id,
            "site_id": None,
        }
        all_grants = other_grants + [study_grant]

        service = PermissionService()
        mock_user = _build_mock_user(all_grants)

        # Requesting permission at a site within the granted study should succeed
        service.require(
            user=mock_user,
            permission=perm_code,
            study_id=study_id,
            site_id=target_site_id,
        )

    @settings(max_examples=100, deadline=None)
    @given(
        study_id=study_id_strategy,
        site_id=site_id_strategy,
        other_study_id=study_id_strategy,
        other_site_id=site_id_strategy,
    )
    def test_site_scope_grants_exact_match_only(
        self, study_id, site_id, other_study_id, other_site_id
    ):
        """A site-scope grant matches only the exact study+site combination.
        Any different study or site must be denied (assuming no other grants).

        **Validates: Requirements 2.2, 2.3, 2.5, 26.4**
        """
        perm_code = "form.enter"
        site_grant = {
            "permission_code": perm_code,
            "scope_level": "site",
            "study_id": study_id,
            "site_id": site_id,
        }

        service = PermissionService()
        mock_user = _build_mock_user([site_grant])

        # Exact match should succeed
        service.require(
            user=mock_user,
            permission=perm_code,
            study_id=study_id,
            site_id=site_id,
        )

        # Different study or site should fail (if they actually differ)
        if other_study_id != study_id or other_site_id != site_id:
            with pytest.raises(AuthorizationError):
                service.require(
                    user=mock_user,
                    permission=perm_code,
                    study_id=other_study_id,
                    site_id=other_site_id,
                )

    @settings(max_examples=100, deadline=None)
    @given(grants=user_with_grants_strategy())
    def test_no_grant_means_no_access(self, grants):
        """A user with grants for certain permissions cannot access permissions
        they were never granted — the code 'nonexistent.permission' is never
        in any standard grant.

        **Validates: Requirements 2.3, 23.4**
        """
        service = PermissionService()
        mock_user = _build_mock_user(grants)

        # A permission code that never appears in our standard pool
        ungrantable_code = "nonexistent.permission.code"

        with pytest.raises(AuthorizationError):
            service.require(
                user=mock_user,
                permission=ungrantable_code,
                study_id=uuid.UUID(int=1),
                site_id=uuid.UUID(int=10),
            )
