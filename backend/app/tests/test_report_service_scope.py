"""Unit tests for Report_Service server-side scope filtering (task 16.1).

Validates Requirements:
  - 9.4: Enrollment Status reports (representative data-backed report).
  - 9.8: Only records within the user's authorization scope are returned.
  - 9.9: An empty result set is returned when nothing is in scope (not an error).
  - 9.10: A request the user is not authorized for is rejected with a
          not-authorized error.

These tests exercise the real ``PermissionService`` against stub users with
varied role scopes and a mocked ``AsyncSession`` that returns the study
universe and the subject-count rows. The scope-filtering behavior is therefore
genuinely tested, not mocked away. The not-authorized behavior (R9.10) is the
same server-side ``PermissionService.require`` check the route guard applies.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AuthorizationError
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
)
from app.schemas.edc.report import EnrollmentStatusReport, ReportResponse
from app.services.edc.report_service import ReportService, report_service
from app.services.shared.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Stub builders (mirrors test_property_scope_filtering)
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


def _make_user(user_roles: list[MagicMock]) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.user_roles = user_roles
    return user


def _user_role(role: MagicMock, study_id=None, site_id=None) -> MagicMock:
    ur = MagicMock(spec=UserRole)
    ur.role = role
    ur.study_id = study_id
    ur.site_id = site_id
    return ur


def _study_scoped_user(study_id: uuid.UUID, code: str = "study.read") -> MagicMock:
    role = _make_role(ScopeLevel.study, [code])
    return _make_user([_user_role(role, study_id=study_id)])


def _system_user(code: str = "study.read") -> MagicMock:
    role = _make_role(ScopeLevel.system, [code])
    return _make_user([_user_role(role)])


def _no_role_user() -> MagicMock:
    return _make_user([])


def _session_returning(study_ids: list[uuid.UUID], subject_rows: list | None = None):
    """Mock an AsyncSession.

    First execute() returns the study universe (``.scalars().all()``); the
    second (only reached when something is in scope) returns the enrollment
    aggregation rows (``.all()``).
    """
    session = AsyncMock()
    universe_result = MagicMock()
    universe_result.scalars.return_value.all.return_value = study_ids

    rows_result = MagicMock()
    rows_result.all.return_value = subject_rows or []

    session.execute = AsyncMock(side_effect=[universe_result, rows_result])
    return session


@pytest.fixture
def service() -> ReportService:
    return ReportService(PermissionService())


# ---------------------------------------------------------------------------
# R9.8 — only in-scope records
# ---------------------------------------------------------------------------


class TestEnrollmentStatusInScopeOnly:
    """Only records within the user's authorization scope are returned (R9.8)."""

    async def test_study_scoped_user_sees_only_their_study(self, service):
        in_scope = uuid.uuid4()
        out_of_scope = uuid.uuid4()
        user = _study_scoped_user(in_scope)

        # Universe has two studies; only the in-scope one survives filtering,
        # so only its subject rows may be queried/returned.
        rows = [MagicMock(study_id=in_scope, status="Enrolled", subject_count=4)]
        session = _session_returning([in_scope, out_of_scope], rows)

        report = await service.enrollment_status(session, user)

        assert isinstance(report, EnrollmentStatusReport)
        assert report.meta.study_ids_in_scope == [in_scope]
        assert all(row.study_id == in_scope for row in report.rows)
        assert out_of_scope not in {row.study_id for row in report.rows}

    async def test_system_user_sees_all_studies(self, service):
        s1, s2 = uuid.uuid4(), uuid.uuid4()
        user = _system_user()
        rows = [
            MagicMock(study_id=s1, status="Enrolled", subject_count=2),
            MagicMock(study_id=s2, status="Screening", subject_count=1),
        ]
        session = _session_returning([s1, s2], rows)

        report = await service.enrollment_status(session, user)

        assert set(report.meta.study_ids_in_scope) == {s1, s2}
        assert report.meta.total == 2


# ---------------------------------------------------------------------------
# R9.9 — empty result set when nothing is in scope
# ---------------------------------------------------------------------------


class TestEnrollmentStatusEmptyWhenNoScope:
    """Empty result set when nothing is in scope — not an error (R9.9)."""

    async def test_no_role_user_gets_empty_report(self, service):
        s1 = uuid.uuid4()
        user = _no_role_user()
        session = _session_returning([s1])

        report = await service.enrollment_status(session, user)

        assert report.rows == []
        assert report.meta.study_ids_in_scope == []
        assert report.meta.total == 0

    async def test_out_of_scope_study_request_is_empty_not_leaky(self, service):
        in_scope = uuid.uuid4()
        other = uuid.uuid4()
        user = _study_scoped_user(in_scope)
        # Requesting a study the user cannot see: the universe query is filtered
        # to that study, which the user is not in scope for → empty.
        session = _session_returning([other])

        report = await service.enrollment_status(session, user, study_id=other)

        assert report.rows == []
        assert report.meta.study_ids_in_scope == []

    async def test_structured_report_empty_when_no_scope(self, service):
        s1 = uuid.uuid4()
        user = _no_role_user()
        session = _session_returning([s1])

        report = await service.data_summary(session, user)

        assert isinstance(report, ReportResponse)
        assert report.rows == []
        assert report.meta.study_ids_in_scope == []
        assert report.meta.report_group == "Data Summary"


# ---------------------------------------------------------------------------
# R9.10 — not-authorized rejection (server-side require)
# ---------------------------------------------------------------------------


class TestNotAuthorizedRejection:
    """A user lacking the required permission is rejected (R9.10).

    The route guard calls ``PermissionService.require`` before the report runs.
    A user with no roles (or without ``study.read`` at the target scope) fails
    this check with an AuthorizationError.
    """

    def test_user_without_permission_is_rejected(self):
        permissions = PermissionService()
        user = _no_role_user()

        with pytest.raises(AuthorizationError):
            permissions.require(user, "study.read")

    def test_study_user_rejected_for_other_study_scope(self):
        permissions = PermissionService()
        in_scope = uuid.uuid4()
        other = uuid.uuid4()
        user = _study_scoped_user(in_scope)

        # Authorized for their study...
        permissions.require(user, "study.read", study_id=in_scope)
        # ...but not for a different study scope.
        with pytest.raises(AuthorizationError):
            permissions.require(user, "study.read", study_id=other)


# ---------------------------------------------------------------------------
# All report groups are scope-filtered surfaces
# ---------------------------------------------------------------------------


class TestAllReportGroupsScopeFiltered:
    """Every Report_Area group returns a scope-filtered envelope (R9.1-R9.8)."""

    @pytest.mark.parametrize(
        "method_name,group",
        [
            ("data_summary", "Data Summary"),
            ("crf_status", "CRF Status"),
            ("query_report", "Query Report"),
            ("ecoa_ediary_report", "eCOA/eDiary Report"),
            ("operational_report", "On-Demand/KRI/Workload/Analysis/Comment/SourceDocTracker"),
            ("end_of_study", "End of Study"),
        ],
    )
    async def test_group_reports_only_in_scope_studies(self, service, method_name, group):
        in_scope = uuid.uuid4()
        out_of_scope = uuid.uuid4()
        user = _study_scoped_user(in_scope)
        session = _session_returning([in_scope, out_of_scope])

        method = getattr(service, method_name)
        report = await method(session, user, study_id=in_scope)

        assert report.meta.report_group == group
        assert report.meta.study_ids_in_scope == [in_scope]
        assert out_of_scope not in report.meta.study_ids_in_scope


class TestReportServiceSingleton:
    def test_singleton_exists(self):
        assert report_service is not None
        assert isinstance(report_service, ReportService)
