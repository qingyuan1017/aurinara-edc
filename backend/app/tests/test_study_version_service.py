"""Unit tests for the StudyVersionService.

Validates Requirements:
  - 5.1: publish() transitions draft → published and records actor/timestamp.
  - 5.2: guard_mutable() rejects modifications to a published version.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.models.edc.study import Study, StudyVersion, StudyVersionStatus
from app.services.designer.study_version_service import StudyVersionService, study_version_service


@pytest.fixture
def service():
    """Fresh StudyVersionService instance for each test."""
    validation_service = MagicMock()
    validation_service.require_publishable = AsyncMock()
    phase_service = MagicMock()
    phase_service.seed_default_phase_flow = AsyncMock()
    return StudyVersionService(
        validation_service=validation_service,
        phase_service=phase_service,
    )


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

    async def test_publish_transitions_draft_to_published(
        self, service, mock_session, draft_version
    ):
        """publish() should set status to published on a draft version."""
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.publish(mock_session, draft_version, actor_id)

        assert result.status == StudyVersionStatus.published

    async def test_publish_records_actor_and_timestamp(self, service, mock_session, draft_version):
        """publish() should record published_by and published_at."""
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.publish(mock_session, draft_version, actor_id)

        assert result.published_by == actor_id
        assert result.published_at is not None

    async def test_publish_writes_audit_event(self, service, mock_session, draft_version):
        """publish() should write an Audit_Event in the same transaction."""
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.publish(mock_session, draft_version, actor_id)

        mock_audit.record.assert_awaited_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["entity_type"] == "study_version"
        assert call_kwargs["entity_id"] == draft_version.id
        assert call_kwargs["action"] == "publish"
        assert call_kwargs["actor_id"] == actor_id

    async def test_publish_rejects_already_published(
        self, service, mock_session, published_version
    ):
        """publish() should raise BusinessRuleError if version is already published."""
        actor_id = uuid.uuid4()

        with pytest.raises(BusinessRuleError, match="not in draft status"):
            await service.publish(mock_session, published_version, actor_id)

    async def test_publish_flushes_session(self, service, mock_session, draft_version):
        """publish() should flush the session (no commit — caller's transaction)."""
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.publish(mock_session, draft_version, actor_id)

        mock_session.flush.assert_awaited_once()

    async def test_publish_rejects_incomplete_design_without_changing_draft(
        self, mock_session, draft_version
    ):
        validation_service = MagicMock()
        validation_service.require_publishable = AsyncMock(
            side_effect=ValidationError("Study design is not ready to publish")
        )
        service = StudyVersionService(validation_service=validation_service)

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            with pytest.raises(ValidationError, match="not ready to publish"):
                await service.publish(mock_session, draft_version, uuid.uuid4())

        assert draft_version.status == StudyVersionStatus.draft
        assert draft_version.published_at is None
        assert draft_version.published_by is None
        mock_audit.record.assert_not_awaited()


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

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_version(mock_session, study_id, "1.0", actor_id=actor_id)

        assert isinstance(result, StudyVersion)
        assert result.study_id == study_id
        assert result.version_number == "1.0"
        assert result.status == StudyVersionStatus.draft

    async def test_create_version_with_amendment_reason(self, service, mock_session):
        """create_version() should store the amendment reason."""
        study_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_version(
                mock_session, study_id, "2.0", amendment_reason="Protocol amendment v2"
            )

        assert result.amendment_reason == "Protocol amendment v2"

    async def test_create_version_writes_audit_event(self, service, mock_session):
        """create_version() should write an Audit_Event."""
        study_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_version(mock_session, study_id, "1.0", actor_id=actor_id)

        mock_audit.record.assert_awaited_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["entity_type"] == "study_version"
        assert call_kwargs["action"] == "create"
        assert call_kwargs["study_id"] == study_id
        assert call_kwargs["actor_id"] == actor_id

    async def test_create_version_seeds_default_subject_phase_flow(self, service, mock_session):
        study_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            version = await service.create_version(
                mock_session,
                study_id,
                "1.0",
                actor_id=actor_id,
            )

        service.phase_service.seed_default_phase_flow.assert_awaited_once_with(
            mock_session,
            design_version_id=version.id,
            study_id=study_id,
            actor_id=actor_id,
        )

    async def test_create_version_adds_to_session(self, service, mock_session):
        """create_version() should add the version to the session and flush."""
        study_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
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


class TestCreateAmendment:
    """Tests for amendment creation and retained published history."""

    @pytest.fixture
    def published_source(self):
        source = StudyVersion(
            id=uuid.uuid4(),
            study_id=uuid.uuid4(),
            version_number="1.0",
            status=StudyVersionStatus.published,
            published_at=datetime.now(UTC),
            published_by=uuid.uuid4(),
        )
        return source

    @pytest.fixture
    def amendment_repository(self, published_source):
        repository = MagicMock()
        repository.latest_published = AsyncMock(return_value=published_source)
        repository.draft_for_study = AsyncMock(return_value=None)
        repository.list_for_study = AsyncMock(return_value=[published_source])
        repository.add = AsyncMock(side_effect=lambda session, version: version)
        return repository

    @pytest.fixture
    def clone_service(self):
        service = MagicMock()
        service.clone_version = AsyncMock(return_value={"forms": 2, "visits": 3})
        return service

    async def test_create_amendment_creates_draft_with_reason_and_source(
        self, mock_session, published_source, amendment_repository, clone_service
    ):
        study = Study(
            id=published_source.study_id,
            study_code="STUDY-001",
            title="Test Study",
            created_by=uuid.uuid4(),
        )
        actor_id = uuid.uuid4()
        service = StudyVersionService(amendment_repository, clone_service=clone_service)

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_amendment(
                mock_session, study, "Protocol amendment v2", actor_id
            )

        assert result.status == StudyVersionStatus.draft
        assert result.version_number == "2.0"
        assert result.amendment_reason == "Protocol amendment v2"
        assert result.amended_from_version_id == published_source.id
        amendment_repository.add.assert_awaited_once_with(mock_session, result)
        clone_service.clone_version.assert_awaited_once_with(
            mock_session,
            source_version_id=published_source.id,
            target_version_id=result.id,
        )
        mock_audit.record.assert_awaited_once()
        assert mock_audit.record.call_args.kwargs["reason"] == "Protocol amendment v2"

    async def test_create_amendment_rejects_blank_reason(
        self, mock_session, published_source, amendment_repository, clone_service
    ):
        study = Study(
            id=published_source.study_id,
            study_code="STUDY-001",
            title="Test Study",
            created_by=uuid.uuid4(),
        )
        service = StudyVersionService(amendment_repository, clone_service=clone_service)

        with pytest.raises(ValidationError, match="Amendment reason is required"):
            await service.create_amendment(mock_session, study, "  ", uuid.uuid4())

        amendment_repository.latest_published.assert_not_awaited()

    async def test_create_amendment_preserves_published_source_and_rejects_second_draft(
        self, mock_session, published_source, amendment_repository, clone_service
    ):
        study = Study(
            id=published_source.study_id,
            study_code="STUDY-001",
            title="Test Study",
            created_by=uuid.uuid4(),
        )
        existing_draft = StudyVersion(
            id=uuid.uuid4(),
            study_id=study.id,
            version_number="2.0",
            status=StudyVersionStatus.draft,
        )
        amendment_repository.draft_for_study.return_value = existing_draft
        service = StudyVersionService(amendment_repository, clone_service=clone_service)

        with pytest.raises(ConflictError, match="draft study version already exists"):
            await service.create_amendment(mock_session, study, "Another change", uuid.uuid4())

        assert published_source.status == StudyVersionStatus.published
        assert published_source.published_by is not None
        amendment_repository.add.assert_not_awaited()

    def test_next_version_number_supports_imported_draft_label(self):
        assert StudyVersionService._next_version_number("Draft V2.0_11-416545") == "3.0"

    async def test_create_amendment_skips_retained_abandoned_version_number(
        self, mock_session, published_source, amendment_repository, clone_service
    ):
        published_source.version_number = "3.0"
        abandoned = StudyVersion(
            id=uuid.uuid4(),
            study_id=published_source.study_id,
            version_number="4.0",
            status=StudyVersionStatus.abandoned,
            abandonment_reason="Superseded draft",
            abandoned_at=datetime.now(UTC),
            abandoned_by=uuid.uuid4(),
        )
        amendment_repository.list_for_study.return_value = [published_source, abandoned]
        study = Study(
            id=published_source.study_id,
            study_code="STUDY-001",
            title="Test Study",
            created_by=uuid.uuid4(),
        )
        service = StudyVersionService(amendment_repository, clone_service=clone_service)

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_amendment(
                mock_session,
                study,
                "Replacement amendment",
                uuid.uuid4(),
            )

        assert result.version_number == "5.0"
        amendment_repository.add.assert_awaited_once_with(mock_session, result)


class TestAbandonDraft:
    """Tests for retained, audited draft abandonment."""

    async def test_abandon_draft_records_reason_actor_timestamp_and_audit(
        self, service, mock_session, draft_version
    ):
        actor_id = uuid.uuid4()
        mock_session.scalar.return_value = None

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.abandon_draft(
                mock_session,
                draft_version,
                "Superseded by a validated import",
                actor_id,
            )

        assert result.status == StudyVersionStatus.abandoned
        assert result.abandoned_by == actor_id
        assert result.abandoned_at is not None
        assert result.abandonment_reason == "Superseded by a validated import"
        mock_audit.record.assert_awaited_once()
        assert mock_audit.record.call_args.kwargs["action"] == "abandon"
        assert mock_audit.record.call_args.kwargs["reason"] == result.abandonment_reason
        mock_session.flush.assert_awaited_once()

    async def test_abandon_rejects_blank_reason_without_mutation(
        self, service, mock_session, draft_version
    ):
        with pytest.raises(ValidationError, match="Abandonment reason is required"):
            await service.abandon_draft(mock_session, draft_version, "  ", uuid.uuid4())

        assert draft_version.status == StudyVersionStatus.draft
        mock_session.scalar.assert_not_awaited()

    async def test_abandon_rejects_published_version(
        self, service, mock_session, published_version
    ):
        with pytest.raises(BusinessRuleError, match="Only a draft"):
            await service.abandon_draft(
                mock_session,
                published_version,
                "No longer needed",
                uuid.uuid4(),
            )

        assert published_version.status == StudyVersionStatus.published
        mock_session.scalar.assert_not_awaited()

    async def test_abandon_rejects_version_referenced_by_subject(
        self, service, mock_session, draft_version
    ):
        mock_session.scalar.return_value = uuid.uuid4()

        with pytest.raises(ConflictError, match="operational subjects"):
            await service.abandon_draft(
                mock_session,
                draft_version,
                "No longer needed",
                uuid.uuid4(),
            )

        assert draft_version.status == StudyVersionStatus.draft


# ---------------------------------------------------------------------------
# Task 3.5 — Edge-case + example tests for publish / amend
# Requirements: 2.1, 2.2, 2.3, 2.10
# ---------------------------------------------------------------------------


class TestPublishValidActorTimestamp:
    """Publish a valid draft: records actor and timestamp (R2.1, R2.2)."""

    async def test_valid_draft_transitions_and_records_actor_and_timestamp(
        self, service, mock_session, draft_version
    ):
        """A valid draft publishes to published and records both actor and timestamp.

        Validates: Requirements 2.1, 2.2
        """
        actor_id = uuid.uuid4()
        before = datetime.now(UTC)

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.publish(mock_session, draft_version, actor_id)

        after = datetime.now(UTC)

        # R2.1: draft → published
        assert result.status == StudyVersionStatus.published
        # R2.2: actor recorded
        assert result.published_by == actor_id
        # R2.2: timestamp recorded and bounded by the call window
        assert result.published_at is not None
        assert before <= result.published_at <= after


class TestPublishValidationSuccessFailure:
    """Publish validation success/failure leaves state consistent (R2.3)."""

    async def test_publish_validation_success(self, service, mock_session, draft_version):
        """A draft that passes validation publishes successfully (R2.3 success path).

        Validates: Requirements 2.1, 2.3
        """
        actor_id = uuid.uuid4()

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.publish(mock_session, draft_version, actor_id)

        assert result.status == StudyVersionStatus.published

    async def test_publish_validation_failure_leaves_version_as_draft(self, service, mock_session):
        """An invalid publish (non-draft) is rejected and the version stays unchanged.

        Validates: Requirements 2.3
        """
        actor_id = uuid.uuid4()
        # A version already published is not a valid publish target.
        version = MagicMock(spec=StudyVersion)
        version.id = uuid.uuid4()
        version.study_id = uuid.uuid4()
        version.status = StudyVersionStatus.published
        prior_published_by = uuid.uuid4()
        prior_published_at = datetime.now(UTC)
        version.published_by = prior_published_by
        version.published_at = prior_published_at

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            with pytest.raises(BusinessRuleError, match="not in draft status"):
                await service.publish(mock_session, version, actor_id)
            # No audit event is written for a rejected publish.
            mock_audit.record.assert_not_awaited()

        # Version is left unchanged (R2.3).
        assert version.status == StudyVersionStatus.published
        assert version.published_by == prior_published_by
        assert version.published_at == prior_published_at


class TestAmendmentReasonBounds:
    """Amendment-reason length boundaries at 0, 1, 4000, 4001 chars (R2.10, R2.9).

    On reject, NO new draft is created.
    """

    @pytest.fixture
    def published_source(self):
        return StudyVersion(
            id=uuid.uuid4(),
            study_id=uuid.uuid4(),
            version_number="1.0",
            status=StudyVersionStatus.published,
            published_at=datetime.now(UTC),
            published_by=uuid.uuid4(),
        )

    @pytest.fixture
    def amendment_repository(self, published_source):
        repository = MagicMock()
        repository.latest_published = AsyncMock(return_value=published_source)
        repository.draft_for_study = AsyncMock(return_value=None)
        repository.list_for_study = AsyncMock(return_value=[published_source])
        repository.add = AsyncMock(side_effect=lambda session, version: version)
        return repository

    @pytest.fixture
    def clone_service(self):
        service = MagicMock()
        service.clone_version = AsyncMock(return_value={})
        return service

    @pytest.fixture
    def study(self, published_source):
        return Study(
            id=published_source.study_id,
            study_code="STUDY-001",
            title="Test Study",
            created_by=uuid.uuid4(),
        )

    async def test_reason_zero_chars_rejected_no_draft(
        self, mock_session, amendment_repository, study, clone_service
    ):
        """0 chars (empty) is rejected and no draft is created (R2.10)."""
        service = StudyVersionService(amendment_repository, clone_service=clone_service)

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            with pytest.raises(ValidationError, match="Amendment reason is required"):
                await service.create_amendment(mock_session, study, "", uuid.uuid4())

        amendment_repository.add.assert_not_awaited()
        mock_audit.record.assert_not_awaited()

    async def test_reason_one_char_accepted_creates_draft(
        self, mock_session, amendment_repository, study, clone_service
    ):
        """1 char (lower bound) is accepted and creates exactly one draft (R2.9, R2.10)."""
        service = StudyVersionService(amendment_repository, clone_service=clone_service)
        reason = "x"

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_amendment(mock_session, study, reason, uuid.uuid4())

        assert result.status == StudyVersionStatus.draft
        assert result.amendment_reason == reason
        amendment_repository.add.assert_awaited_once()

    async def test_reason_four_thousand_chars_accepted_creates_draft(
        self, mock_session, amendment_repository, study, clone_service
    ):
        """4000 chars (upper bound) is accepted and creates exactly one draft (R2.9, R2.10)."""
        service = StudyVersionService(amendment_repository, clone_service=clone_service)
        reason = "a" * 4000

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.create_amendment(mock_session, study, reason, uuid.uuid4())

        assert result.status == StudyVersionStatus.draft
        assert len(result.amendment_reason) == 4000
        amendment_repository.add.assert_awaited_once()

    async def test_reason_four_thousand_one_chars_rejected_no_draft(
        self, mock_session, amendment_repository, study, clone_service
    ):
        """4001 chars (over bound) is rejected and no draft is created (R2.10)."""
        service = StudyVersionService(amendment_repository, clone_service=clone_service)
        reason = "a" * 4001

        with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            with pytest.raises(ValidationError, match="must not exceed 4000 characters"):
                await service.create_amendment(mock_session, study, reason, uuid.uuid4())

        amendment_repository.add.assert_not_awaited()
        mock_audit.record.assert_not_awaited()
