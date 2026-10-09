"""Property-based test for the Report_Area scope-filtering invariant.

# Feature: designer-edc-refactor, Property 12: Report scope-filtering invariant

**Validates: Requirements 9.8, 9.9**

Requirement 9.8: WHEN an authorized Operational_Role user requests any
Report_Area report, THE EDC_Module SHALL return only records within the user's
authorization scope.

Requirement 9.9: WHEN an authorized Operational_Role user requests a Report_Area
report for which no records fall within the user's authorization scope, THE
EDC_Module SHALL return an empty result set rather than records outside that
scope.

The property, universally quantified over varied authorization scopes and study
universes:

  - every returned row's ``study_id`` lies within the user's in-scope set
    (never an out-of-scope study's records);
  - ``meta.study_ids_in_scope`` is exactly the intersection of the study
    universe and the user's scope;
  - when that intersection is empty, ``rows == []`` and no error is raised.

Users are generated with three authorization shapes — system scope (sees every
study), study scope over a random subset of the universe, and no roles (sees
nothing). The real ``PermissionService`` performs the scope filtering (mirroring
``test_report_service_scope.py``); only the ``AsyncSession`` is mocked, returning
the generated study universe and the enrollment rows for the in-scope studies.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
)
from app.schemas.edc.report import EnrollmentStatusReport
from app.services.edc.report_service import ReportService
from app.services.shared.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Stub builders (mirror test_report_service_scope.py)
# ---------------------------------------------------------------------------


def _make_role(scope_level: ScopeLevel, codes: list[str]) -> MagicMock:
    role = MagicMock(spec=Role)
    role.scope_level = scope_level
    rps = []
    for code in codes:
        perm = MagicMock(spec=Permission)
        perm.code = code
        rp = MagicMock(spec=RolePermission)
        rp.permission = perm
        rps.append(rp)
    role.role_permissions = rps
    return role


def _user_role(role: MagicMock, study_id=None, site_id=None) -> MagicMock:
    ur = MagicMock(spec=UserRole)
    ur.role = role
    ur.study_id = study_id
    ur.site_id = site_id
    return ur


def _make_user(user_roles: list[MagicMock]) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.user_roles = user_roles
    return user


def _system_user(code: str = "study.read") -> MagicMock:
    role = _make_role(ScopeLevel.system, [code])
    return _make_user([_user_role(role)])


def _study_scoped_user(study_ids: list[uuid.UUID], code: str = "study.read") -> MagicMock:
    """A user with one study-scope role assignment per in-scope study."""
    user_roles = [
        _user_role(_make_role(ScopeLevel.study, [code]), study_id=sid)
        for sid in study_ids
    ]
    return _make_user(user_roles)


def _no_role_user() -> MagicMock:
    return _make_user([])


def _session_returning(study_ids: list[uuid.UUID], subject_rows: list | None = None):
    """Mock an AsyncSession.

    The first ``execute()`` returns the study universe (``.scalars().all()``);
    the second (only reached when something is in scope) returns the enrollment
    aggregation rows (``.all()``).
    """
    session = AsyncMock()
    universe_result = MagicMock()
    universe_result.scalars.return_value.all.return_value = study_ids

    rows_result = MagicMock()
    rows_result.all.return_value = subject_rows or []

    session.execute = AsyncMock(side_effect=[universe_result, rows_result])
    return session


# ---------------------------------------------------------------------------
# Strategies: a (study-universe, user-scope) scenario
# ---------------------------------------------------------------------------

_SCOPE_KINDS = ("system", "study_subset", "none")


@st.composite
def report_scope_scenario(draw):
    """Generate a study universe paired with a user authorization scope.

    Returns a dict with:
      - ``universe``: the full list of study IDs the universe query would yield
      - ``scope_kind``: one of system / study_subset / none
      - ``user_in_scope``: the set of study IDs the user's roles authorize
        (over the whole generated id-space, not only the universe)
    """
    universe = draw(st.lists(st.uuids(), min_size=0, max_size=8, unique=True))
    scope_kind = draw(st.sampled_from(_SCOPE_KINDS))

    # Studies the user's roles are assigned to. These may include ids that are
    # not in the universe (a user can hold a role for a study not currently in
    # the queried universe) and may omit some universe studies.
    extra_studies = draw(st.lists(st.uuids(), min_size=0, max_size=4, unique=True))

    if scope_kind == "system":
        user_in_scope: set[uuid.UUID] | None = None  # None => sees everything
    elif scope_kind == "study_subset":
        # Random subset of the universe, optionally plus some out-of-universe ids.
        subset = draw(st.lists(st.sampled_from(universe), unique=True)) if universe else []
        user_in_scope = set(subset) | set(extra_studies)
    else:  # none
        user_in_scope = set()

    return {
        "universe": universe,
        "scope_kind": scope_kind,
        "user_in_scope": user_in_scope,
    }


def _build_user(scenario: dict) -> MagicMock:
    kind = scenario["scope_kind"]
    if kind == "system":
        return _system_user()
    if kind == "none":
        return _no_role_user()
    return _study_scoped_user(sorted(scenario["user_in_scope"], key=str))


def _expected_in_scope(scenario: dict) -> list[uuid.UUID]:
    """Intersection of the universe and the user's scope, in universe order."""
    universe = scenario["universe"]
    user_in_scope = scenario["user_in_scope"]
    if user_in_scope is None:  # system scope
        return list(universe)
    return [sid for sid in universe if sid in user_in_scope]


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestReportScopeFilteringInvariant:
    """Property 12 — reports expose only in-scope records, empty when none."""

    @settings(max_examples=150, deadline=None)
    @given(scenario=report_scope_scenario())
    def test_enrollment_report_is_scope_filtered(self, scenario):
        """A report returns only in-scope records; empty (not error) when none.

        # Feature: designer-edc-refactor, Property 12: Report scope-filtering invariant
        **Validates: Requirements 9.8, 9.9**
        """
        service = ReportService(PermissionService())
        user = _build_user(scenario)
        expected = _expected_in_scope(scenario)

        # The report only queries enrollment rows for in-scope studies, so the
        # mocked rows are built from the expected intersection. Each in-scope
        # study contributes a row; this lets us assert no out-of-scope row can
        # ever appear in the output.
        subject_rows = [
            MagicMock(study_id=sid, status="Enrolled", subject_count=1)
            for sid in expected
        ]
        session = _session_returning(scenario["universe"], subject_rows)

        report = asyncio.run(service.enrollment_status(session, user))

        assert isinstance(report, EnrollmentStatusReport)

        # (1) meta.study_ids_in_scope is exactly the universe ∩ user-scope.
        assert report.meta.study_ids_in_scope == expected, (
            f"study_ids_in_scope mismatch: got {report.meta.study_ids_in_scope}, "
            f"expected {expected}"
        )

        # (2) Every returned row's study_id is within the in-scope set — never
        #     an out-of-scope study's records (R9.8).
        in_scope_set = set(expected)
        for row in report.rows:
            assert row.study_id in in_scope_set, (
                f"row for out-of-scope study {row.study_id} leaked into report"
            )

        # (3) When the intersection is empty, rows == [] and no error raised (R9.9).
        if not expected:
            assert report.rows == []
            assert report.meta.total == 0

    @settings(max_examples=100, deadline=None)
    @given(scenario=report_scope_scenario())
    def test_out_of_scope_single_study_request_is_empty(self, scenario):
        """Requesting a single out-of-scope study yields an empty report, not a leak.

        # Feature: designer-edc-refactor, Property 12: Report scope-filtering invariant
        **Validates: Requirements 9.8, 9.9**

        Picks a study the user is NOT authorized for and requests it explicitly.
        The universe query is narrowed to that study server-side, the user is out
        of scope for it, so the report must be empty and raise no error.
        """
        user = _build_user(scenario)

        # Find a study the user cannot see. For system users none exists, so the
        # property is vacuous (skip by asserting trivially).
        user_in_scope = scenario["user_in_scope"]
        if user_in_scope is None:
            return  # system scope sees everything; nothing is out of scope

        out_of_scope_id = uuid.uuid4()
        while out_of_scope_id in user_in_scope:
            out_of_scope_id = uuid.uuid4()

        service = ReportService(PermissionService())
        # The narrowed universe query returns just the requested study.
        session = _session_returning([out_of_scope_id])

        report = asyncio.run(
            service.enrollment_status(session, user, study_id=out_of_scope_id)
        )

        assert report.rows == []
        assert report.meta.study_ids_in_scope == []
        assert report.meta.total == 0
