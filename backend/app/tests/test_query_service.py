"""Unit tests for the QueryService.

Validates Requirements:
  - 13.1: create_query links the query to exactly one affected object.
  - 13.2: Query statuses Open, Answered, Closed, Reopened, Cancelled.
  - 13.3: respond transitions Open/Reopened → Answered and appends message.
  - 13.4: close transitions Open/Answered → Closed with closing actor/timestamp.
  - 13.5: reopen transitions Closed → Reopened.
  - 13.6: Complete threaded message history preserved.
  - 13.7: Every query action writes an Audit_Event.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.query import Query, QueryMessage, QueryStatus, QueryTargetType, QueryType
from app.services.query_service import QueryService, query_service


@pytest.fixture
def service():
    """Fresh QueryService instance for each test."""
    return QueryService()


@pytest.fixture
def mock_session():
    """Mock AsyncSession that tracks add/flush calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def actor_id():
    """Actor UUID for audit purposes."""
    return uuid.uuid4()


@pytest.fixture
def study_id():
    """Study UUID."""
    return uuid.uuid4()


def _make_query(
    study_id: uuid.UUID | None = None,
    status: QueryStatus = QueryStatus.open,
    site_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
) -> Query:
    """Create a Query instance for testing."""
    return Query(
        id=uuid.uuid4(),
        study_id=study_id or uuid.uuid4(),
        site_id=site_id,
        subject_id=subject_id,
        target_type=QueryTargetType.form_instance,
        target_id=uuid.uuid4(),
        text="Please clarify the value",
        query_type=QueryType.manual,
        status=status,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
        messages=[],
    )


class TestCreateQuery:
    """Tests for QueryService.create_query()."""

    async def test_create_query_persists_with_status_open(
        self, service, mock_session, actor_id, study_id
    ):
        """create_query creates a Query with status Open and correct target (Req 13.1, 13.2)."""
        target_id = uuid.uuid4()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            query = await service.create_query(
                mock_session,
                study_id=study_id,
                target_type=QueryTargetType.form_instance,
                target_id=target_id,
                text="Please clarify this value",
                actor_id=actor_id,
            )

        assert query.study_id == study_id
        assert query.target_type == QueryTargetType.form_instance
        assert query.target_id == target_id
        assert query.text == "Please clarify this value"
        assert query.status == QueryStatus.open
        assert query.created_by == actor_id
        assert query.query_type == QueryType.manual
        mock_session.add.assert_called_once_with(query)

    async def test_create_query_with_optional_context(
        self, service, mock_session, actor_id, study_id
    ):
        """create_query accepts optional site_id and subject_id."""
        site_id = uuid.uuid4()
        subject_id = uuid.uuid4()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            query = await service.create_query(
                mock_session,
                study_id=study_id,
                target_type=QueryTargetType.subject,
                target_id=subject_id,
                text="Missing data",
                actor_id=actor_id,
                site_id=site_id,
                subject_id=subject_id,
            )

        assert query.site_id == site_id
        assert query.subject_id == subject_id

    async def test_create_query_writes_audit_event(
        self, service, mock_session, actor_id, study_id
    ):
        """create_query writes an Audit_Event (Req 13.7)."""
        target_id = uuid.uuid4()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_query(
                mock_session,
                study_id=study_id,
                target_type=QueryTargetType.field,
                target_id=target_id,
                text="Check this",
                actor_id=actor_id,
            )

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "query"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["actor_id"] == actor_id
            assert call_kwargs["study_id"] == study_id

    async def test_create_query_system_type(
        self, service, mock_session, actor_id, study_id
    ):
        """create_query supports system-generated query type."""
        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            query = await service.create_query(
                mock_session,
                study_id=study_id,
                target_type=QueryTargetType.form_record,
                target_id=uuid.uuid4(),
                text="System check failed",
                actor_id=actor_id,
                query_type=QueryType.system,
            )

        assert query.query_type == QueryType.system


class TestRespond:
    """Tests for QueryService.respond()."""

    async def test_respond_transitions_open_to_answered(
        self, service, mock_session, actor_id
    ):
        """respond transitions Open → Answered (Req 13.3)."""
        query = _make_query(status=QueryStatus.open)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.respond(
                mock_session, query, "Here is the clarification", actor_id
            )

        assert result.status == QueryStatus.answered
        assert result.updated_at is not None

    async def test_respond_transitions_reopened_to_answered(
        self, service, mock_session, actor_id
    ):
        """respond transitions Reopened → Answered (Req 13.3)."""
        query = _make_query(status=QueryStatus.reopened)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.respond(
                mock_session, query, "Updated response", actor_id
            )

        assert result.status == QueryStatus.answered

    async def test_respond_appends_message_to_thread(
        self, service, mock_session, actor_id
    ):
        """respond appends a QueryMessage to the thread (Req 13.6)."""
        query = _make_query(status=QueryStatus.open)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.respond(
                mock_session, query, "My response message", actor_id
            )

        # Verify a QueryMessage was added to the session
        added_objects = [call.args[0] for call in mock_session.add.call_args_list]
        messages = [obj for obj in added_objects if isinstance(obj, QueryMessage)]
        assert len(messages) == 1
        assert messages[0].message == "My response message"
        assert messages[0].author_id == actor_id
        assert messages[0].query_id == query.id

    async def test_respond_rejects_closed_query(
        self, service, mock_session, actor_id
    ):
        """respond raises BusinessRuleError for Closed queries."""
        query = _make_query(status=QueryStatus.closed)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.respond(mock_session, query, "msg", actor_id)

        assert "Cannot respond" in exc_info.value.message

    async def test_respond_rejects_cancelled_query(
        self, service, mock_session, actor_id
    ):
        """respond raises BusinessRuleError for Cancelled queries."""
        query = _make_query(status=QueryStatus.cancelled)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.respond(mock_session, query, "msg", actor_id)

        assert "Cannot respond" in exc_info.value.message

    async def test_respond_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """respond writes an Audit_Event (Req 13.7)."""
        query = _make_query(status=QueryStatus.open)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.respond(mock_session, query, "response", actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "query"
            assert call_kwargs["action"] == "respond"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == str(QueryStatus.open)
            assert call_kwargs["new_value"] == str(QueryStatus.answered)


class TestClose:
    """Tests for QueryService.close()."""

    async def test_close_transitions_open_to_closed(
        self, service, mock_session, actor_id
    ):
        """close transitions Open → Closed (Req 13.4)."""
        query = _make_query(status=QueryStatus.open)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.close(mock_session, query, actor_id)

        assert result.status == QueryStatus.closed
        assert result.closed_at is not None
        assert result.closed_by == actor_id

    async def test_close_transitions_answered_to_closed(
        self, service, mock_session, actor_id
    ):
        """close transitions Answered → Closed (Req 13.4)."""
        query = _make_query(status=QueryStatus.answered)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.close(mock_session, query, actor_id)

        assert result.status == QueryStatus.closed
        assert result.closed_by == actor_id

    async def test_close_transitions_reopened_to_closed(
        self, service, mock_session, actor_id
    ):
        """close transitions Reopened → Closed (per design state diagram)."""
        query = _make_query(status=QueryStatus.reopened)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.close(mock_session, query, actor_id)

        assert result.status == QueryStatus.closed
        assert result.closed_by == actor_id

    async def test_close_rejects_cancelled_query(
        self, service, mock_session, actor_id
    ):
        """close raises BusinessRuleError for Cancelled queries."""
        query = _make_query(status=QueryStatus.cancelled)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.close(mock_session, query, actor_id)

        assert "Cannot close" in exc_info.value.message

    async def test_close_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """close writes an Audit_Event (Req 13.7)."""
        query = _make_query(status=QueryStatus.answered)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.close(mock_session, query, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "query"
            assert call_kwargs["action"] == "close"
            assert call_kwargs["old_value"] == str(QueryStatus.answered)
            assert call_kwargs["new_value"] == str(QueryStatus.closed)


class TestReopen:
    """Tests for QueryService.reopen()."""

    async def test_reopen_transitions_closed_to_reopened(
        self, service, mock_session, actor_id
    ):
        """reopen transitions Closed → Reopened (Req 13.5)."""
        query = _make_query(status=QueryStatus.closed)
        query.closed_at = datetime.now(UTC)
        query.closed_by = uuid.uuid4()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.reopen(mock_session, query, actor_id)

        assert result.status == QueryStatus.reopened
        assert result.closed_at is None
        assert result.closed_by is None
        assert result.updated_at is not None

    async def test_reopen_rejects_open_query(
        self, service, mock_session, actor_id
    ):
        """reopen raises BusinessRuleError for Open queries."""
        query = _make_query(status=QueryStatus.open)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.reopen(mock_session, query, actor_id)

        assert "Cannot reopen" in exc_info.value.message

    async def test_reopen_rejects_answered_query(
        self, service, mock_session, actor_id
    ):
        """reopen raises BusinessRuleError for Answered queries."""
        query = _make_query(status=QueryStatus.answered)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.reopen(mock_session, query, actor_id)

        assert "Cannot reopen" in exc_info.value.message

    async def test_reopen_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """reopen writes an Audit_Event (Req 13.7)."""
        query = _make_query(status=QueryStatus.closed)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.reopen(mock_session, query, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "query"
            assert call_kwargs["action"] == "reopen"
            assert call_kwargs["old_value"] == str(QueryStatus.closed)
            assert call_kwargs["new_value"] == str(QueryStatus.reopened)


class TestCancel:
    """Tests for QueryService.cancel()."""

    async def test_cancel_transitions_open_to_cancelled(
        self, service, mock_session, actor_id
    ):
        """cancel transitions Open → Cancelled."""
        query = _make_query(status=QueryStatus.open)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.cancel(mock_session, query, actor_id)

        assert result.status == QueryStatus.cancelled
        assert result.updated_at is not None

    async def test_cancel_transitions_answered_to_cancelled(
        self, service, mock_session, actor_id
    ):
        """cancel transitions Answered → Cancelled."""
        query = _make_query(status=QueryStatus.answered)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.cancel(mock_session, query, actor_id)

        assert result.status == QueryStatus.cancelled

    async def test_cancel_rejects_closed_query(
        self, service, mock_session, actor_id
    ):
        """cancel raises BusinessRuleError for Closed queries."""
        query = _make_query(status=QueryStatus.closed)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.cancel(mock_session, query, actor_id)

        assert "Cannot cancel" in exc_info.value.message

    async def test_cancel_rejects_reopened_query(
        self, service, mock_session, actor_id
    ):
        """cancel raises BusinessRuleError for Reopened queries."""
        query = _make_query(status=QueryStatus.reopened)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.cancel(mock_session, query, actor_id)

        assert "Cannot cancel" in exc_info.value.message

    async def test_cancel_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """cancel writes an Audit_Event (Req 13.7)."""
        query = _make_query(status=QueryStatus.open)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.cancel(mock_session, query, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "query"
            assert call_kwargs["action"] == "cancel"
            assert call_kwargs["old_value"] == str(QueryStatus.open)
            assert call_kwargs["new_value"] == str(QueryStatus.cancelled)


class TestGetQuery:
    """Tests for QueryService.get_query()."""

    async def test_get_query_returns_query(self, service, mock_session):
        """get_query returns the query when found."""
        expected_query = _make_query()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected_query
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_query(mock_session, expected_query.id)
        assert result == expected_query

    async def test_get_query_raises_not_found(self, service, mock_session):
        """get_query raises NotFoundError when no query exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_query(mock_session, uuid.uuid4())

        assert "not found" in exc_info.value.message


class TestListQueries:
    """Tests for QueryService.list_queries()."""

    async def test_list_queries_returns_paginated_response(
        self, service, study_id
    ):
        """list_queries returns a PaginatedResponse."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        from app.api.deps import PaginationParams

        pagination = PaginationParams(page=1, page_size=25)
        result = await service.list_queries(
            mock_session, study_id, pagination=pagination
        )

        assert result.page == 1
        assert result.page_size == 25
        assert result.total == 0
        assert result.items == []


class TestQueryServiceSingleton:
    """Tests for the module-level singleton."""

    def test_singleton_exists(self):
        """The module exports a singleton query_service instance."""
        assert query_service is not None
        assert isinstance(query_service, QueryService)
