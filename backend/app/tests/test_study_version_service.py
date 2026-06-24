"""Unit tests for the StudyVersionService.

Validates Requirements:
  - 5.1: publish() transitions draft → published and records actor/timestamp.
  - 5.2: guard_mutable() rejects modifications to a published version.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.study import StudyVersion, StudyVersionStatus
from app.services.study_version_service import StudyVersionService, study_version_service


@pytest.fixture
def service():
    """Fresh StudyVersionService instance for each test."""
    return StudyVersionService()


@pytest.fixture
def mock_session():
    """Mock AsyncSession that tracks add/flush calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def draft_version():
    """A StudyVersion in draft status."""
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    version.version_number = "1.0"
    version.status = StudyVersionStatus.draft
    version.published_at = None
    version.published_by = None
    return version


@pytest.fixture
def published_version():
    """A StudyVersion in published status."""
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    version.version_number = "1.0"
    version.status = StudyVersionStatus.published
    version.published_at = datetime.now(UTC)
    version.published_by = uuid.uuid4()
    return version


class TestPublish:
    """Tests for StudyVersionService.publish()."""

    async def test_publish_transitions_draft_to_published(self, service, mock_session, draft_version):
        """publish() should set status to published on a draft version."""
        actor_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.publish(mock_session, draft_version, actor_id)

        assert result.status == StudyVersionStatus.published

    async def test_publish_records_actor_and_timestamp(self, service, mock_session, draft_version):
        """publish() should record published_by and published_at."""
        actor_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.publish(mock_session, draft_version, actor_id)

        assert result.published_by == actor_id
        assert result.published_at is not None

    async def test_publish_writes_audit_event(self, service, mock_session, draft_version):
        """publish() should write an Audit_Event in the same transaction."""
        actor_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.publish(mock_session, draft_version, actor_id)

        mock_audit.record.assert_awaited_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["entity_type"] == "study_version"
        assert call_kwargs["entity_id"] == draft_version.id
        assert call_kwargs["action"] == "publish"
        assert call_kwargs["actor_id"] == actor_id

    async def test_publish_rejects_already_published(self, service, mock_session, published_version):
        """publish() should raise BusinessRuleError if version is already published."""
        actor_id = uuid.uuid4()

        with pytest.raises(BusinessRuleError, match="not in draft status"):
            await service.publish(mock_session, published_version, actor_id)

    async def test_publish_flushes_session(self, service, mock_session, draft_version):
        """publish() should flush the session (no commit — caller's transaction)."""
        actor_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.publish(mock_session, draft_version, actor_id)

        mock_session.flush.assert_awaited_once()


class TestGuardMutable:
    """Tests for StudyVersionService.guard_mutable()."""

    def test_guard_mutable_allows_draft(self, service, draft_version):
        """guard_mutable() should not raise for a draft version."""
        # Should not raise
        service.guard_mutable(draft_version)

    def test_guard_mutable_rejects_published(self, service, published_version):
        """guard_mutable() should raise BusinessRuleError for a published version."""
        with pytest.raises(BusinessRuleError, match="Cannot modify a published study version"):
            service.guard_mutable(published_version)


class TestCreateVersion:
    """Tests for StudyVersionService.create_version()."""

    async def test_create_version_creates_draft(self, service, mock_session):
        """create_version() should create a new version in draft status."""
        study_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_version(
                mock_session, study_id, "1.0", actor_id=actor_id
            )

        assert isinstance(result, StudyVersion)
        assert result.study_id == study_id
        assert result.version_number == "1.0"
        assert result.status == StudyVersionStatus.draft

    async def test_create_version_with_amendment_reason(self, service, mock_session):
        """create_version() should store the amendment reason."""
        study_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_version(
                mock_session, study_id, "2.0", amendment_reason="Protocol amendment v2"
            )

        assert result.amendment_reason == "Protocol amendment v2"

    async def test_create_version_writes_audit_event(self, service, mock_session):
        """create_version() should write an Audit_Event."""
        study_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_version(mock_session, study_id, "1.0", actor_id=actor_id)

        mock_audit.record.assert_awaited_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["entity_type"] == "study_version"
        assert call_kwargs["action"] == "create"
        assert call_kwargs["study_id"] == study_id
        assert call_kwargs["actor_id"] == actor_id

    async def test_create_version_adds_to_session(self, service, mock_session):
        """create_version() should add the version to the session and flush."""
        study_id = uuid.uuid4()

        with patch("app.services.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_version(mock_session, study_id, "1.0")

        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited()


class TestGetVersion:
    """Tests for StudyVersionService.get_version()."""

    async def test_get_version_returns_version(self, service):
        """get_version() should return the version when found."""
        version_id = uuid.uuid4()
        mock_version = MagicMock(spec=StudyVersion)
        mock_version.id = version_id

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_version
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_version(mock_session, version_id)
        assert result == mock_version

    async def test_get_version_raises_not_found(self, service):
        """get_version() should raise NotFoundError when version does not exist."""
        version_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError, match="Study version not found"):
            await service.get_version(mock_session, version_id)


class TestSingleton:
    """Tests for the module-level singleton."""

    def test_singleton_exists(self):
        """The module exports a singleton study_version_service instance."""
        assert study_version_service is not None
        assert isinstance(study_version_service, StudyVersionService)
