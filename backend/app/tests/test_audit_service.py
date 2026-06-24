"""Unit tests for the AuditService.

Validates Requirements:
  - 18.1: record() captures all required audit fields.
  - 18.3: record() stores reason for change.
  - 18.5: search() applies filters correctly.
  - 18.6: export() returns flat dicts for export.
  - 21.4: record() writes within the caller's transaction (no commit).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit import AuditService, audit_service
from app.models.audit import AuditEvent
from app.schemas.audit import AuditSearchFilters


@pytest.fixture
def service():
    """Fresh AuditService instance for each test."""
    return AuditService()


@pytest.fixture
def mock_session():
    """Mock AsyncSession that tracks add/flush calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


class TestAuditServiceRecord:
    """Tests for AuditService.record()."""

    async def test_record_creates_event_with_all_fields(self, service, mock_session):
        """record() should create an AuditEvent with all provided fields."""
        actor_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        study_id = uuid.uuid4()
        site_id = uuid.uuid4()
        subject_id = uuid.uuid4()

        event = await service.record(
            mock_session,
            entity_type="form_instance",
            entity_id=entity_id,
            action="update",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            field_name="blood_pressure",
            old_value="120/80",
            new_value="130/85",
            reason="Transcription error corrected",
            actor_id=actor_id,
            actor_email="clinician@example.com",
            request_id="req-abc-123",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
        )

        assert event.entity_type == "form_instance"
        assert event.entity_id == entity_id
        assert event.action == "update"
        assert event.study_id == study_id
        assert event.site_id == site_id
        assert event.subject_id == subject_id
        assert event.field_name == "blood_pressure"
        assert event.old_value == "120/80"
        assert event.new_value == "130/85"
        assert event.reason == "Transcription error corrected"
        assert event.actor_id == actor_id
        assert event.actor_email == "clinician@example.com"
        assert event.request_id == "req-abc-123"
        assert event.ip_address == "192.168.1.100"
        assert event.user_agent == "Mozilla/5.0"

    async def test_record_adds_to_session_without_commit(self, service, mock_session):
        """record() must add to session and flush, but NOT commit (Requirement 21.4)."""
        event = await service.record(
            mock_session,
            entity_type="subject",
            entity_id=uuid.uuid4(),
            action="create",
            actor_id=uuid.uuid4(),
            request_id="req-001",
        )

        mock_session.add.assert_called_once_with(event)
        mock_session.flush.assert_awaited_once()
        # Verify commit is NOT called — caller's transaction boundary handles it
        mock_session.commit.assert_not_awaited()

    async def test_record_auto_populates_actor_from_context(self, service, mock_session):
        """record() should use request context actor when not explicitly provided."""
        ctx_actor = uuid.uuid4()

        with patch("app.core.audit.get_actor", return_value=ctx_actor):
            event = await service.record(
                mock_session,
                entity_type="study",
                entity_id=uuid.uuid4(),
                action="create",
                request_id="req-002",
            )

        assert event.actor_id == ctx_actor

    async def test_record_auto_populates_request_id_from_context(self, service, mock_session):
        """record() should use request context request_id when not explicitly provided."""
        ctx_request_id = "ctx-req-id-456"

        with patch("app.core.audit.get_request_id", return_value=ctx_request_id):
            event = await service.record(
                mock_session,
                entity_type="study",
                entity_id=uuid.uuid4(),
                action="create",
                actor_id=uuid.uuid4(),
            )

        assert event.request_id == ctx_request_id

    async def test_record_explicit_params_override_context(self, service, mock_session):
        """Explicitly provided actor_id and request_id override context values."""
        explicit_actor = uuid.uuid4()
        explicit_request_id = "explicit-req-789"

        with (
            patch("app.core.audit.get_actor", return_value=uuid.uuid4()),
            patch("app.core.audit.get_request_id", return_value="context-req-id"),
        ):
            event = await service.record(
                mock_session,
                entity_type="study",
                entity_id=uuid.uuid4(),
                action="update",
                actor_id=explicit_actor,
                request_id=explicit_request_id,
            )

        assert event.actor_id == explicit_actor
        assert event.request_id == explicit_request_id

    async def test_record_stores_reason_for_change(self, service, mock_session):
        """record() stores reason field (Requirement 18.3)."""
        event = await service.record(
            mock_session,
            entity_type="form_instance",
            entity_id=uuid.uuid4(),
            action="update",
            field_name="dose",
            old_value="100mg",
            new_value="150mg",
            reason="Dose adjustment per protocol amendment",
            actor_id=uuid.uuid4(),
            request_id="req-003",
        )

        assert event.reason == "Dose adjustment per protocol amendment"

    async def test_record_returns_audit_event_instance(self, service, mock_session):
        """record() returns an AuditEvent model instance."""
        event = await service.record(
            mock_session,
            entity_type="site",
            entity_id=uuid.uuid4(),
            action="create",
            actor_id=uuid.uuid4(),
            request_id="req-004",
        )

        assert isinstance(event, AuditEvent)


class TestAuditServiceSearch:
    """Tests for AuditService.search()."""

    async def test_search_builds_query_with_filters(self, service):
        """search() should construct the correct query based on provided filters."""
        mock_session = AsyncMock()
        # Mock execute to return empty result for paginate
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        filters = AuditSearchFilters(
            actor_id=uuid.uuid4(),
            entity_type="subject",
            action="create",
        )

        result = await service.search(mock_session, filters=filters)

        # Should call execute at least once (count + data queries)
        assert mock_session.execute.await_count >= 1
        assert result.items == []
        assert result.total == 0

    async def test_search_with_no_filters(self, service):
        """search() with empty filters returns all events (paginated)."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        filters = AuditSearchFilters()

        result = await service.search(mock_session, filters=filters)

        assert result.page == 1
        assert result.page_size == 25
        assert result.total == 0


class TestAuditServiceExport:
    """Tests for AuditService.export()."""

    async def test_export_returns_list_of_dicts(self, service):
        """export() should return a list of flat dictionaries."""
        mock_event = MagicMock(spec=AuditEvent)
        mock_event.id = uuid.uuid4()
        mock_event.actor_id = uuid.uuid4()
        mock_event.actor_email = "user@example.com"
        mock_event.timestamp = datetime.now(UTC)
        mock_event.entity_type = "subject"
        mock_event.entity_id = uuid.uuid4()
        mock_event.study_id = uuid.uuid4()
        mock_event.site_id = None
        mock_event.subject_id = None
        mock_event.action = "create"
        mock_event.field_name = None
        mock_event.old_value = None
        mock_event.new_value = None
        mock_event.reason = None
        mock_event.request_id = uuid.uuid4()
        mock_event.ip_address = "10.0.0.1"
        mock_event.user_agent = "TestAgent/1.0"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_session.execute = AsyncMock(return_value=mock_result)

        filters = AuditSearchFilters(entity_type="subject")
        result = await service.export(mock_session, filters=filters)

        assert isinstance(result, list)
        assert len(result) == 1
        row = result[0]
        assert isinstance(row, dict)
        assert row["entity_type"] == "subject"
        assert row["action"] == "create"
        assert row["actor_email"] == "user@example.com"
        # UUIDs serialized as strings for export
        assert row["id"] == str(mock_event.id)
        assert row["entity_id"] == str(mock_event.entity_id)

    async def test_export_empty_result(self, service):
        """export() with no matching events returns empty list."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        filters = AuditSearchFilters(action="nonexistent_action")
        result = await service.export(mock_session, filters=filters)

        assert result == []


class TestAuditServiceSingleton:
    """Tests for the module-level singleton."""

    def test_singleton_exists(self):
        """The module exports a singleton audit_service instance."""
        assert audit_service is not None
        assert isinstance(audit_service, AuditService)
