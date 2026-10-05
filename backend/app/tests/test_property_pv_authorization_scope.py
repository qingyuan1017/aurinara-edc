"""Property-based test for PV safety authorization scope.

**Validates: Requirements 1, 2, 11, 12, 16, 19, 23**

Property 5: Safety authorization scope.

*For any* User, PV Permission, Study, Site, and PV object, the operation succeeds
exactly when the shared ``Authorization_Scope`` contains the required permission at
the target scope; otherwise no safety, audit, attachment, export, or projection
state changes and list endpoints return only in-scope records or an empty list.

The property drives the real shared ``PermissionService`` (the single server-side
authority reused by PV) together with the real ``AuthorizationScope`` resolution.
It uses deterministic in-memory identity objects (``User``/``Role``/``UserRole``/
``RolePermission``/``Permission``) and an in-memory fake that models a PV safety
operation whose state mutation is gated exactly the way ``app/api/deps.py``
gates PV routes: resolve the required PV permission at the object's study/site
scope, then assert object-level access, and only then mutate safety/audit/
attachment/export/projection state. No database, worker, network, or external
service is used.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import PV_PERMISSION_CODES
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
    UserStatus,
)
from app.services.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Deterministic in-memory identity construction
# ---------------------------------------------------------------------------

# A small fixed pool of study/site identifiers so grants and targets frequently
# overlap; using a tiny pool makes both the "authorized" and "denied" branches
# occur often across generated examples.
STUDY_IDS: list[uuid.UUID] = [uuid.UUID(int=i) for i in range(1, 4)]
SITE_IDS: list[uuid.UUID] = [uuid.UUID(int=100 + i) for i in range(1, 4)]

PV_CODES: list[str] = sorted(PV_PERMISSION_CODES)


def _make_permission(code: str) -> Permission:
    return Permission(id=uuid.uuid4(), code=code)


def _build_user(grants: list[tuple[str, str, int | None, int | None]]) -> User:
    """Build an in-memory User whose role assignments encode ``grants``.

    Each grant is ``(permission_code, scope_level, study_index, site_index)``.
    ``study_index``/``site_index`` index into ``STUDY_IDS``/``SITE_IDS`` or are
    ``None`` for a broader scope. One single-permission Role is created per grant
    so the resolved ``Authorization_Scope`` is exactly the generated set.
    """
    user = User(
        id=uuid.uuid4(),
        email=f"pv-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        first_name="Safety",
        last_name="Actor",
        status=UserStatus.active,
    )
    user.user_roles = []

    for code, scope_level, study_idx, site_idx in grants:
        permission = _make_permission(code)
        role = Role(
            id=uuid.uuid4(),
            name=f"role-{uuid.uuid4().hex[:8]}",
            scope_level=ScopeLevel(scope_level),
            is_system=True,
        )
        role.role_permissions = [
            RolePermission(role_id=role.id, permission_id=permission.id)
        ]
        # Attach the permission object onto the association so resolve_scope can
        # walk role_permission.permission.code without a database.
        role.role_permissions[0].permission = permission

        study_id = STUDY_IDS[study_idx] if study_idx is not None else None
        site_id = SITE_IDS[site_idx] if site_idx is not None else None

        user_role = UserRole(
            id=uuid.uuid4(),
            user_id=user.id,
            role_id=role.id,
            study_id=study_id,
            site_id=site_id,
        )
        user_role.role = role
        user.user_roles.append(user_role)

    return user


# ---------------------------------------------------------------------------
# In-memory PV state + gated operation (models app/api/deps.py enforcement)
# ---------------------------------------------------------------------------


@dataclass
class PVState:
    """All PV-owned state a denied operation must leave untouched."""

    safety: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    exports: list = field(default_factory=list)
    projection: list = field(default_factory=list)

    def snapshot(self) -> tuple[int, int, int, int, int]:
        return (
            len(self.safety),
            len(self.audit),
            len(self.attachments),
            len(self.exports),
            len(self.projection),
        )


@dataclass(frozen=True)
class PVObject:
    """A PV safety target object carrying its canonical study/site scope."""

    study_id: uuid.UUID | None
    site_id: uuid.UUID | None


def _perform_pv_operation(
    service: PermissionService,
    user: User,
    permission: str,
    obj: PVObject,
    state: PVState,
) -> bool:
    """Attempt a PV safety mutation gated by the shared permission checks.

    Mirrors ``require_pv_object_access`` in ``app/api/deps.py``: resolve the
    required PV permission at the object's study/site scope, then assert
    object-level access. Only when both pass does the operation mutate PV
    state (writing safety data plus its atomic audit event, and touching the
    other PV stores). Returns True on success, False when access was denied.
    """
    try:
        service.require(user, permission, study_id=obj.study_id, site_id=obj.site_id)
        service.assert_object_access(user, obj)
    except (AuthorizationError, AuthenticationError):
        return False

    # Authorized: mutate every PV-owned store the property enumerates.
    state.safety.append((permission, obj))
    state.audit.append((permission, obj))  # atomic PV safety Audit_Event
    state.attachments.append(obj)
    state.exports.append(obj)
    state.projection.append(obj)
    return True


# ---------------------------------------------------------------------------
# Reference oracle for the authorization decision
# ---------------------------------------------------------------------------


def _expected_authorized(
    grants: list[tuple[str, str, int | None, int | None]],
    permission: str,
    study_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
) -> bool:
    """Independent oracle: does any grant satisfy permission@(study, site)?

    A system grant (no study, no site) matches anything. A study grant matches
    the same study (any site within it). A site grant matches only the exact
    study+site.
    """
    for code, _scope, study_idx, site_idx in grants:
        if code != permission:
            continue
        g_study = STUDY_IDS[study_idx] if study_idx is not None else None
        g_site = SITE_IDS[site_idx] if site_idx is not None else None

        if g_study is None and g_site is None:
            return True
        if g_study is not None and g_site is None and study_id == g_study:
            return True
        if (
            g_study is not None
            and g_site is not None
            and study_id == g_study
            and site_id == g_site
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_pv_code = st.sampled_from(PV_CODES)
_study_idx = st.one_of(st.none(), st.integers(min_value=0, max_value=len(STUDY_IDS) - 1))
_site_idx = st.one_of(st.none(), st.integers(min_value=0, max_value=len(SITE_IDS) - 1))


@st.composite
def _grant(draw) -> tuple[str, str, int | None, int | None]:
    """Generate one internally consistent (code, scope, study, site) grant."""
    code = draw(_pv_code)
    scope = draw(st.sampled_from(["system", "study", "site"]))
    if scope == "system":
        return (code, scope, None, None)
    study_idx = draw(st.integers(min_value=0, max_value=len(STUDY_IDS) - 1))
    if scope == "study":
        return (code, scope, study_idx, None)
    site_idx = draw(st.integers(min_value=0, max_value=len(SITE_IDS) - 1))
    return (code, scope, study_idx, site_idx)


_grants = st.lists(_grant(), min_size=0, max_size=6)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestPVAuthorizationScopeProperty:
    """Property 5 — safety authorization scope.

    **Validates: Requirements 1, 2, 11, 12, 16, 19, 23**
    """

    @settings(max_examples=200, deadline=None)
    @given(
        grants=_grants,
        req_permission=_pv_code,
        target_study_idx=_study_idx,
        target_site_idx=_site_idx,
    )
    def test_operation_succeeds_exactly_when_scope_contains_permission_and_target(
        self,
        grants: list[tuple[str, str, int | None, int | None]],
        req_permission: str,
        target_study_idx: int | None,
        target_site_idx: int | None,
    ):
        """Success iff scope holds the required permission at the target scope;
        otherwise no PV state changes at all.
        """
        service = PermissionService()
        user = _build_user(grants)

        target_study = (
            STUDY_IDS[target_study_idx] if target_study_idx is not None else None
        )
        # A site target only makes sense within a study.
        target_site = (
            SITE_IDS[target_site_idx]
            if target_site_idx is not None and target_study is not None
            else None
        )
        obj = PVObject(study_id=target_study, site_id=target_site)

        expected = _expected_authorized(
            grants, req_permission, target_study, target_site
        )
        # assert_object_access additionally requires *some* grant covering the
        # object scope. When the object has no study scope, only a system grant
        # qualifies. Fold that into the oracle for the object-level branch.
        if expected:
            has_system = any(s == "system" for _c, s, _st, _si in grants)
            covers_object = has_system or any(
                (
                    st_ is not None
                    and (STUDY_IDS[st_] == target_study)
                    and (si_ is None or (target_site is not None and SITE_IDS[si_] == target_site))
                )
                for _c, _s, st_, si_ in grants
            )
            if target_study is None:
                expected = has_system
            else:
                expected = expected and covers_object

        state = PVState()
        before = state.snapshot()

        succeeded = _perform_pv_operation(
            service, user, req_permission, obj, state
        )

        assert succeeded == expected

        if succeeded:
            # Exactly one write into every PV store, including the atomic audit.
            assert state.snapshot() == (
                before[0] + 1,
                before[1] + 1,
                before[2] + 1,
                before[3] + 1,
                before[4] + 1,
            )
        else:
            # Denied: no safety, audit, attachment, export, or projection change.
            assert state.snapshot() == before

    @settings(max_examples=200, deadline=None)
    @given(grants=_grants)
    def test_list_endpoints_return_only_in_scope_records_or_empty(
        self,
        grants: list[tuple[str, str, int | None, int | None]],
    ):
        """``filter_studies``/``filter_sites`` return only in-scope resources.

        A user with no grants (empty scope) gets an empty list. Otherwise the
        result is a subset of the requested resources containing exactly those
        the resolved scope authorizes.
        """
        service = PermissionService()
        user = _build_user(grants)

        candidate_studies = list(STUDY_IDS)
        candidate_sites = list(SITE_IDS)
        # Map each candidate site to a study so study-scope grants cover sites.
        site_study = {SITE_IDS[i]: STUDY_IDS[i] for i in range(len(SITE_IDS))}

        filtered_studies = service.filter_studies(user, candidate_studies)
        filtered_sites = service.filter_sites(user, candidate_sites, site_study)

        # Results never exceed the candidate set and preserve subset semantics.
        assert set(filtered_studies).issubset(set(candidate_studies))
        assert set(filtered_sites).issubset(set(candidate_sites))

        has_system = any(s == "system" for _c, s, _st, _si in grants)
        grant_study_ids = {
            STUDY_IDS[st_] for _c, _s, st_, _si in grants if st_ is not None
        }
        grant_site_ids = {
            SITE_IDS[si_] for _c, _s, _st, si_ in grants if si_ is not None
        }

        if has_system:
            assert set(filtered_studies) == set(candidate_studies)
            assert set(filtered_sites) == set(candidate_sites)
        else:
            assert set(filtered_studies) == {
                sid for sid in candidate_studies if sid in grant_study_ids
            }
            expected_sites = {
                site
                for site in candidate_sites
                if site in grant_site_ids or site_study.get(site) in grant_study_ids
            }
            assert set(filtered_sites) == expected_sites

        if not grants:
            # Empty scope yields empty lists (never a leak of all records).
            assert filtered_studies == []
            assert filtered_sites == []

    @settings(max_examples=100, deadline=None)
    @given(
        grants=_grants,
        req_permission=_pv_code,
        target_study_idx=st.integers(min_value=0, max_value=len(STUDY_IDS) - 1),
    )
    def test_inactive_user_is_denied_and_changes_no_state(
        self,
        grants: list[tuple[str, str, int | None, int | None]],
        req_permission: str,
        target_study_idx: int,
    ):
        """A deactivated account is denied regardless of granted permissions,
        and the denied operation mutates no PV state (Requirement 1.4)."""
        service = PermissionService()
        user = _build_user(grants)
        user.status = UserStatus.inactive

        obj = PVObject(study_id=STUDY_IDS[target_study_idx], site_id=None)
        state = PVState()
        before = state.snapshot()

        succeeded = _perform_pv_operation(
            service, user, req_permission, obj, state
        )

        assert succeeded is False
        assert state.snapshot() == before
