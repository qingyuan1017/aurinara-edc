"""Unit tests for the DashboardService.

Validates Requirements:
  - 20.1: Study dashboard: subject counts by status, form completion, open queries.
  - 20.2: Site dashboard: site-level progress.
  - 20.3: Query metrics: open/answered/overdue counts and aging.
  - 20.4: All metrics computed strictly within the caller's Authorization_Scope (read-only).
  - 4.4: Study dashboard accessible from study management.
  - 6.3: Site dashboard accessible from site management.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.query import QueryStatus
from app.models.subject import SubjectStatus
from app.schemas.dashboard import QueryMetrics, SiteDashboard, StudyDashboard
from app.services.dashboard_service import (
    OVERDUE_THRESHOLD_DAYS,
    DashboardService,
    dashboard_service,
)


@pytest.fixture
def service():
    """Fresh DashboardService instance for each test."""
    return DashboardService()


@pytest.fixture
def study_id():
    """Study UUID."""
    return uuid.uuid4()


@pytest.fixture
def site_id():
    """Site UUID."""
    return uuid.uuid4()


def _mock_session_with_results(results_sequence: list):
    """Create a mock session that returns results in sequence.

    Each element in results_sequence is what session.execute() returns
    on successive calls.
    """
    session = AsyncMock()
    execute_returns = []

    for result_data in results_sequence:
        mock_result = MagicMock()
        if isinstance(result_data, list):
            # For queries returning rows (.all())
            mock_result.all.return_value = result_data
            mock_result.scalars.return_value.all.return_value = result_data
        elif isinstance(result_data, tuple):
            # For queries returning a single row (.one())
            mock_row = MagicMock()
            # Support named tuple-like access
            for attr, val in result_data:
                setattr(mock_row, attr, val)
            mock_result.one.return_value = mock_row
        elif isinstance(result_data, int):
            # For scalar_one() results (counts)
            mock_result.scalar_one.return_value = result_data
        execute_returns.append(mock_result)

    session.execute = AsyncMock(side_effect=execute_returns)
    return session


class TestStudyDashboard:
    """Tests for DashboardService.study_dashboard() (Req 20.1, 4.4)."""

    async def test_study_dashboard_returns_correct_type(self, service, study_id):
        """study_dashboard returns a StudyDashboard instance."""
        # Mock: subject counts, form completion, open query count
        mock_session = _mock_session_with_results([
            # subject_counts_by_status: list of (status, cnt) rows
            [
                MagicMock(status=SubjectStatus.screening, cnt=5),
                MagicMock(status=SubjectStatus.enrolled, cnt=12),
            ],
            # form_completion: single row with total and submitted
            (("total", 30), ("submitted", 20)),
            # open_query_count: scalar
            7,
        ])

        result = await service.study_dashboard(mock_session, study_id)

        assert isinstance(result, StudyDashboard)

    async def test_study_dashboard_subject_counts(self, service, study_id):
        """study_dashboard returns subject counts grouped by status."""
        mock_session = _mock_session_with_results([
            [
                MagicMock(status=SubjectStatus.screening, cnt=3),
                MagicMock(status=SubjectStatus.enrolled, cnt=8),
                MagicMock(status=SubjectStatus.completed, cnt=2),
            ],
            (("total", 0), ("submitted", 0)),
            0,
        ])

        result = await service.study_dashboard(mock_session, study_id)

        assert result.subject_counts_by_status[SubjectStatus.screening] == 3
        assert result.subject_counts_by_status[SubjectStatus.enrolled] == 8
        assert result.subject_counts_by_status[SubjectStatus.completed] == 2

    async def test_study_dashboard_form_completion(self, service, study_id):
        """study_dashboard returns total and submitted form instance counts."""
        mock_session = _mock_session_with_results([
            [],
            (("total", 50), ("submitted", 35)),
            0,
        ])

        result = await service.study_dashboard(mock_session, study_id)

        assert result.total_form_instances == 50
        assert result.submitted_form_instances == 35

    async def test_study_dashboard_open_query_count(self, service, study_id):
        """study_dashboard returns the count of open/reopened queries."""
        mock_session = _mock_session_with_results([
            [],
            (("total", 0), ("submitted", 0)),
            15,
        ])

        result = await service.study_dashboard(mock_session, study_id)

        assert result.open_query_count == 15

    async def test_study_dashboard_empty_study(self, service, study_id):
        """study_dashboard handles a study with no data."""
        mock_session = _mock_session_with_results([
            [],
            (("total", 0), ("submitted", 0)),
            0,
        ])

        result = await service.study_dashboard(mock_session, study_id)

        assert result.subject_counts_by_status == {}
        assert result.total_form_instances == 0
        assert result.submitted_form_instances == 0
        assert result.open_query_count == 0


class TestSiteDashboard:
    """Tests for DashboardService.site_dashboard() (Req 20.2, 6.3)."""

    async def test_site_dashboard_returns_correct_type(self, service, site_id):
        """site_dashboard returns a SiteDashboard instance."""
        mock_session = _mock_session_with_results([
            [MagicMock(status=SubjectStatus.enrolled, cnt=5)],
            (("total", 10), ("submitted", 8)),
            3,
        ])

        result = await service.site_dashboard(mock_session, site_id)

        assert isinstance(result, SiteDashboard)

    async def test_site_dashboard_subject_counts(self, service, site_id):
        """site_dashboard returns subject counts for the site."""
        mock_session = _mock_session_with_results([
            [
                MagicMock(status=SubjectStatus.screening, cnt=2),
                MagicMock(status=SubjectStatus.on_treatment, cnt=4),
            ],
            (("total", 0), ("submitted", 0)),
            0,
        ])

        result = await service.site_dashboard(mock_session, site_id)

        assert result.subject_counts_by_status[SubjectStatus.screening] == 2
        assert result.subject_counts_by_status[SubjectStatus.on_treatment] == 4

    async def test_site_dashboard_form_completion(self, service, site_id):
        """site_dashboard returns form completion for the site."""
        mock_session = _mock_session_with_results([
            [],
            (("total", 20), ("submitted", 15)),
            0,
        ])

        result = await service.site_dashboard(mock_session, site_id)

        assert result.total_form_instances == 20
        assert result.submitted_form_instances == 15

    async def test_site_dashboard_open_query_count(self, service, site_id):
        """site_dashboard returns open/reopened query count for the site."""
        mock_session = _mock_session_with_results([
            [],
            (("total", 0), ("submitted", 0)),
            9,
        ])

        result = await service.site_dashboard(mock_session, site_id)

        assert result.open_query_count == 9


class TestQueryMetrics:
    """Tests for DashboardService.query_metrics() (Req 20.3)."""

    async def test_query_metrics_returns_correct_type(self, service, study_id):
        """query_metrics returns a QueryMetrics instance."""
        mock_session = AsyncMock()
        # First call: status counts
        status_result = MagicMock()
        status_result.all.return_value = [
            MagicMock(status=QueryStatus.open, cnt=5),
            MagicMock(status=QueryStatus.answered, cnt=3),
            MagicMock(status=QueryStatus.closed, cnt=10),
        ]
        # Second call: open query dates for aging
        dates_result = MagicMock()
        dates_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[status_result, dates_result]
        )

        result = await service.query_metrics(mock_session, study_id)

        assert isinstance(result, QueryMetrics)

    async def test_query_metrics_counts_by_status(self, service, study_id):
        """query_metrics returns correct counts per status."""
        mock_session = AsyncMock()
        status_result = MagicMock()
        status_result.all.return_value = [
            MagicMock(status=QueryStatus.open, cnt=4),
            MagicMock(status=QueryStatus.reopened, cnt=2),
            MagicMock(status=QueryStatus.answered, cnt=6),
            MagicMock(status=QueryStatus.closed, cnt=15),
            MagicMock(status=QueryStatus.cancelled, cnt=1),
        ]
        dates_result = MagicMock()
        dates_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[status_result, dates_result]
        )

        result = await service.query_metrics(mock_session, study_id)

        # Open count includes both Open and Reopened
        assert result.open_count == 6  # 4 + 2
        assert result.answered_count == 6
        assert result.closed_count == 15
        assert result.cancelled_count == 1

    async def test_query_metrics_overdue_detection(self, service, study_id):
        """query_metrics identifies overdue queries (open > 14 days)."""
        now = datetime.now(UTC)
        mock_session = AsyncMock()

        status_result = MagicMock()
        status_result.all.return_value = [
            MagicMock(status=QueryStatus.open, cnt=3),
        ]

        # 3 open queries: 2 overdue (>14 days), 1 recent
        dates_result = MagicMock()
        dates_result.scalars.return_value.all.return_value = [
            now - timedelta(days=20),  # overdue
            now - timedelta(days=16),  # overdue
            now - timedelta(days=5),   # not overdue
        ]

        mock_session.execute = AsyncMock(
            side_effect=[status_result, dates_result]
        )

        result = await service.query_metrics(mock_session, study_id)

        assert result.overdue_count == 2

    async def test_query_metrics_average_days_open(self, service, study_id):
        """query_metrics computes average days open for open queries."""
        now = datetime.now(UTC)
        mock_session = AsyncMock()

        status_result = MagicMock()
        status_result.all.return_value = [
            MagicMock(status=QueryStatus.open, cnt=2),
        ]

        # Two open queries: one 10 days old, one 20 days old → avg = 15
        dates_result = MagicMock()
        dates_result.scalars.return_value.all.return_value = [
            now - timedelta(days=10),
            now - timedelta(days=20),
        ]

        mock_session.execute = AsyncMock(
            side_effect=[status_result, dates_result]
        )

        result = await service.query_metrics(mock_session, study_id)

        # Average should be approximately 15 days (might differ by fractions)
        assert 14.9 <= result.average_days_open <= 15.1

    async def test_query_metrics_no_open_queries(self, service, study_id):
        """query_metrics handles zero open queries gracefully."""
        mock_session = AsyncMock()

        status_result = MagicMock()
        status_result.all.return_value = [
            MagicMock(status=QueryStatus.closed, cnt=10),
        ]

        dates_result = MagicMock()
        dates_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[status_result, dates_result]
        )

        result = await service.query_metrics(mock_session, study_id)

        assert result.open_count == 0
        assert result.overdue_count == 0
        assert result.average_days_open == 0.0

    async def test_query_metrics_overdue_threshold_is_14_days(self, service):
        """The overdue threshold constant is 14 days."""
        assert OVERDUE_THRESHOLD_DAYS == 14


class TestDashboardServiceSingleton:
    """Tests for the module-level singleton."""

    def test_singleton_exists(self):
        """The module exports a singleton dashboard_service instance."""
        assert dashboard_service is not None
        assert isinstance(dashboard_service, DashboardService)
