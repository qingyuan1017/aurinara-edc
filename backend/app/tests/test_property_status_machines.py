"""Property-based test for status-machine transitions.

**Validates: Requirements 4.3, 5.1, 7.3, 13.2, 13.3, 13.4, 13.5, 19.1**

Property 8: Only legal status transitions are accepted.

For any entity governed by a status machine (study, subject, query, export job)
and any attempted transition, the transition succeeds if and only if it is
permitted by that entity's defined state machine; illegal transitions are
rejected with a BusinessRuleError and leave the state unchanged.

Generates random current states and random target states for each machine and
verifies:
1. Legal transitions succeed (service doesn't raise)
2. Illegal transitions raise BusinessRuleError
3. The entity's state is unchanged after an illegal transition attempt
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError
from app.models.export import Export, ExportStatus
from app.models.query import Query, QueryStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.services.export_service import ExportService
from app.services.query_service import QueryService
from app.services.study_service import StudyService
from app.services.subject_service import SubjectService


# ---------------------------------------------------------------------------
# Legal transition maps (mirroring the service implementations)
# ---------------------------------------------------------------------------

STUDY_LEGAL_TRANSITIONS: dict[StudyStatus, set[StudyStatus]] = {
    StudyStatus.draft: {StudyStatus.uat},
    StudyStatus.uat: {StudyStatus.active},
    StudyStatus.active: {StudyStatus.enrollment_closed},
    StudyStatus.enrollment_closed: {StudyStatus.locked},
    StudyStatus.locked: {StudyStatus.archived},
    StudyStatus.archived: set(),
}

SUBJECT_LEGAL_TRANSITIONS: dict[SubjectStatus, set[SubjectStatus]] = {
    SubjectStatus.screening: {SubjectStatus.screen_failed, SubjectStatus.enrolled},
    SubjectStatus.enrolled: {
        SubjectStatus.randomized,
        SubjectStatus.withdrawn,
        SubjectStatus.early_terminated,
    },
    SubjectStatus.randomized: {SubjectStatus.on_treatment},
    SubjectStatus.on_treatment: {
        SubjectStatus.completed,
        SubjectStatus.early_terminated,
        SubjectStatus.lost_to_follow_up,
        SubjectStatus.withdrawn,
    },
    SubjectStatus.screen_failed: set(),
    SubjectStatus.completed: set(),
    SubjectStatus.early_terminated: set(),
    SubjectStatus.lost_to_follow_up: set(),
    SubjectStatus.withdrawn: set(),
}

# Query transitions are action-based: respond, close, reopen, cancel
# respond: Open/Reopened → Answered
# close: Open/Answered/Reopened → Closed
# reopen: Closed → Reopened
# cancel: Open/Answered → Cancelled
QUERY_RESPOND_FROM = {QueryStatus.open, QueryStatus.reopened}
QUERY_CLOSE_FROM = {QueryStatus.open, QueryStatus.answered, QueryStatus.reopened}
QUERY_REOPEN_FROM = {QueryStatus.closed}
QUERY_CANCEL_FROM = {QueryStatus.open, QueryStatus.answered}

# Derive legal transitions for query as a combined map
QUERY_LEGAL_TRANSITIONS: dict[QueryStatus, set[QueryStatus]] = {
    QueryStatus.open: {QueryStatus.answered, QueryStatus.closed, QueryStatus.cancelled},
    QueryStatus.answered: {QueryStatus.closed, QueryStatus.cancelled},
    QueryStatus.closed: {QueryStatus.reopened},
    QueryStatus.reopened: {QueryStatus.answered, QueryStatus.closed},
    QueryStatus.cancelled: set(),
}

EXPORT_LEGAL_TRANSITIONS: dict[ExportStatus, set[ExportStatus]] = {
    ExportStatus.queued: {ExportStatus.running},
    ExportStatus.running: {ExportStatus.completed, ExportStatus.failed},
    ExportStatus.completed: set(),
    ExportStatus.failed: set(),
}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

study_status_strategy = st.sampled_from(list(StudyStatus))
subject_status_strategy = st.sampled_from(list(SubjectStatus))
query_status_strategy = st.sampled_from(list(QueryStatus))
export_status_strategy = st.sampled_from(list(ExportStatus))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session() -> AsyncMock:
    """Create a mock async session that tracks all relevant calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = MagicMock()
    session.refresh = AsyncMock()
    return session


def _make_study(status: StudyStatus) -> MagicMock:
    """Create a Study mock with the given status."""
    study = MagicMock(spec=Study)
    study.id = uuid.uuid4()
    study.study_code = "TEST-001"
    study.title = "Test Study"
    study.status = status
    study.created_by = uuid.uuid4()
    study.created_at = datetime.now(UTC)
    study.updated_at = None
    study.deleted_at = None
    return study


def _make_subject(status: SubjectStatus) -> MagicMock:
    """Create a Subject mock with the given status."""
    subject = MagicMock(spec=Subject)
    subject.id = uuid.uuid4()
    subject.study_id = uuid.uuid4()
    subject.site_id = uuid.uuid4()
    subject.study_version_id = uuid.uuid4()
    subject.subject_number = "SITE01-0001"
    subject.status = status
    subject.created_by = uuid.uuid4()
    subject.created_at = datetime.now(UTC)
    subject.updated_at = None
    subject.deleted_at = None
    return subject


def _make_query(status: QueryStatus) -> MagicMock:
    """Create a Query mock with the given status."""
    query = MagicMock(spec=Query)
    query.id = uuid.uuid4()
    query.study_id = uuid.uuid4()
    query.site_id = uuid.uuid4()
    query.subject_id = uuid.uuid4()
    query.target_type = "Form_Instance"
    query.target_id = uuid.uuid4()
    query.text = "Test query"
    query.query_type = "manual"
    query.status = status
    query.created_by = uuid.uuid4()
    query.created_at = datetime.now(UTC)
    query.updated_at = None
    query.closed_at = None
    query.closed_by = None
    return query


def _make_export(status: ExportStatus) -> MagicMock:
    """Create an Export mock with the given status."""
    export = MagicMock(spec=Export)
    export.id = uuid.uuid4()
    export.study_id = uuid.uuid4()
    export.export_type = "csv"
    export.status = status
    export.filters = None
    export.file_path = None
    export.file_size = None
    export.error_message = None
    export.requested_by = uuid.uuid4()
    export.created_at = datetime.now(UTC)
    export.started_at = None
    export.completed_at = None
    return export


# ---------------------------------------------------------------------------
# Property 8: Only legal status transitions are accepted
# ---------------------------------------------------------------------------


class TestStudyStatusMachineProperty:
    """Property tests for Study status transitions.

    **Validates: Requirements 4.3**

    Study lifecycle: Draft → UAT → Active → Enrollment Closed → Locked → Archived
    (linear, no skipping).
    """

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=study_status_strategy,
        target_status=study_status_strategy,
    )
    async def test_study_legal_transitions_succeed(
        self, current_status: StudyStatus, target_status: StudyStatus
    ):
        """Legal study status transitions succeed without raising.

        **Validates: Requirements 4.3**
        """
        allowed = STUDY_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            return  # Skip illegal transitions in this test

        service = StudyService()
        session = _make_mock_session()
        study = _make_study(current_status)
        actor_id = uuid.uuid4()

        with patch("app.services.study_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.transition_status(
                session, study, target_status, actor_id
            )

        assert result.status == target_status

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=study_status_strategy,
        target_status=study_status_strategy,
    )
    async def test_study_illegal_transitions_raise(
        self, current_status: StudyStatus, target_status: StudyStatus
    ):
        """Illegal study status transitions raise BusinessRuleError.

        **Validates: Requirements 4.3**
        """
        allowed = STUDY_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status in allowed:
            return  # Skip legal transitions in this test

        service = StudyService()
        session = _make_mock_session()
        study = _make_study(current_status)
        actor_id = uuid.uuid4()
        original_status = study.status

        with pytest.raises(BusinessRuleError):
            await service.transition_status(session, study, target_status, actor_id)

        # State is unchanged after illegal transition
        assert study.status == original_status


class TestSubjectStatusMachineProperty:
    """Property tests for Subject status transitions.

    **Validates: Requirements 7.3**

    Subject lifecycle:
        Screening → {Screen Failed, Enrolled}
        Enrolled → {Randomized, Withdrawn, Early Terminated}
        Randomized → On Treatment
        On Treatment → {Completed, Early Terminated, Lost to Follow-up, Withdrawn}
    """

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=subject_status_strategy,
        target_status=subject_status_strategy,
    )
    async def test_subject_legal_transitions_succeed(
        self, current_status: SubjectStatus, target_status: SubjectStatus
    ):
        """Legal subject status transitions succeed without raising.

        **Validates: Requirements 7.3**
        """
        allowed = SUBJECT_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            return  # Skip illegal transitions in this test

        service = SubjectService()
        session = _make_mock_session()
        subject = _make_subject(current_status)
        actor_id = uuid.uuid4()

        with patch("app.services.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.transition_status(
                session, subject, target_status, actor_id
            )

        assert result.status == target_status

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=subject_status_strategy,
        target_status=subject_status_strategy,
    )
    async def test_subject_illegal_transitions_raise(
        self, current_status: SubjectStatus, target_status: SubjectStatus
    ):
        """Illegal subject status transitions raise BusinessRuleError.

        **Validates: Requirements 7.3**
        """
        allowed = SUBJECT_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status in allowed:
            return  # Skip legal transitions in this test

        service = SubjectService()
        session = _make_mock_session()
        subject = _make_subject(current_status)
        actor_id = uuid.uuid4()
        original_status = subject.status

        with pytest.raises(BusinessRuleError):
            await service.transition_status(session, subject, target_status, actor_id)

        # State is unchanged after illegal transition
        assert subject.status == original_status


class TestQueryStatusMachineProperty:
    """Property tests for Query status transitions.

    **Validates: Requirements 13.2, 13.3, 13.4, 13.5**

    Query lifecycle:
        Open → {Answered, Closed, Cancelled}
        Answered → {Closed, Cancelled}
        Closed → Reopened
        Reopened → {Answered, Closed}
    """

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=query_status_strategy,
        target_status=query_status_strategy,
    )
    async def test_query_legal_transitions_succeed(
        self, current_status: QueryStatus, target_status: QueryStatus
    ):
        """Legal query status transitions succeed without raising.

        **Validates: Requirements 13.2, 13.3, 13.4, 13.5**
        """
        allowed = QUERY_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            return  # Skip illegal transitions in this test

        service = QueryService()
        session = _make_mock_session()
        query = _make_query(current_status)
        actor_id = uuid.uuid4()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()

            # Route to the correct action based on target_status
            if target_status == QueryStatus.answered:
                result = await service.respond(
                    session, query, "Test response", actor_id
                )
            elif target_status == QueryStatus.closed:
                result = await service.close(session, query, actor_id)
            elif target_status == QueryStatus.reopened:
                result = await service.reopen(session, query, actor_id)
            elif target_status == QueryStatus.cancelled:
                result = await service.cancel(session, query, actor_id)
            else:
                return  # No action for this target

        assert result.status == target_status

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=query_status_strategy,
        target_status=query_status_strategy,
    )
    async def test_query_illegal_transitions_raise(
        self, current_status: QueryStatus, target_status: QueryStatus
    ):
        """Illegal query status transitions raise BusinessRuleError.

        **Validates: Requirements 13.2, 13.3, 13.4, 13.5**
        """
        allowed = QUERY_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status in allowed:
            return  # Skip legal transitions in this test

        service = QueryService()
        session = _make_mock_session()
        query = _make_query(current_status)
        actor_id = uuid.uuid4()
        original_status = query.status

        # Attempt illegal transition via the appropriate action
        if target_status == QueryStatus.answered:
            with pytest.raises(BusinessRuleError):
                await service.respond(session, query, "Test response", actor_id)
        elif target_status == QueryStatus.closed:
            with pytest.raises(BusinessRuleError):
                await service.close(session, query, actor_id)
        elif target_status == QueryStatus.reopened:
            with pytest.raises(BusinessRuleError):
                await service.reopen(session, query, actor_id)
        elif target_status == QueryStatus.cancelled:
            with pytest.raises(BusinessRuleError):
                await service.cancel(session, query, actor_id)
        else:
            # target_status == QueryStatus.open — no action leads to Open status
            # so there's nothing to test here
            return

        # State is unchanged after illegal transition
        assert query.status == original_status


class TestExportStatusMachineProperty:
    """Property tests for Export status transitions.

    **Validates: Requirements 19.1**

    Export lifecycle: Queued → Running → {Completed, Failed}
    """

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=export_status_strategy,
        target_status=export_status_strategy,
    )
    async def test_export_legal_transitions_succeed(
        self, current_status: ExportStatus, target_status: ExportStatus
    ):
        """Legal export status transitions succeed without raising.

        **Validates: Requirements 19.1**
        """
        allowed = EXPORT_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            return  # Skip illegal transitions in this test

        service = ExportService()
        session = _make_mock_session()
        export = _make_export(current_status)

        # Route to the correct action based on target_status
        if target_status == ExportStatus.running:
            result = await service.start_export(session, export)
        elif target_status == ExportStatus.completed:
            result = await service.complete_export(
                session, export, file_path="/exports/test.csv", file_size=1024
            )
        elif target_status == ExportStatus.failed:
            result = await service.fail_export(
                session, export, error_message="Test error"
            )
        else:
            return  # No action for this target

        assert result.status == target_status

    @settings(max_examples=100, deadline=None)
    @given(
        current_status=export_status_strategy,
        target_status=export_status_strategy,
    )
    async def test_export_illegal_transitions_raise(
        self, current_status: ExportStatus, target_status: ExportStatus
    ):
        """Illegal export status transitions raise BusinessRuleError.

        **Validates: Requirements 19.1**
        """
        allowed = EXPORT_LEGAL_TRANSITIONS.get(current_status, set())
        if target_status in allowed:
            return  # Skip legal transitions in this test

        service = ExportService()
        session = _make_mock_session()
        export = _make_export(current_status)
        original_status = export.status

        # Attempt illegal transition via the appropriate action
        if target_status == ExportStatus.running:
            with pytest.raises(BusinessRuleError):
                await service.start_export(session, export)
        elif target_status == ExportStatus.completed:
            with pytest.raises(BusinessRuleError):
                await service.complete_export(
                    session, export, file_path="/exports/test.csv", file_size=1024
                )
        elif target_status == ExportStatus.failed:
            with pytest.raises(BusinessRuleError):
                await service.fail_export(
                    session, export, error_message="Test error"
                )
        else:
            # target_status == ExportStatus.queued — no action leads to Queued
            return

        # State is unchanged after illegal transition
        assert export.status == original_status
