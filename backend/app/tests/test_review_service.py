"""Unit tests for ReviewService.

Validates Requirements 15.1-15.4: review toggles, actor/timestamp retention,
scoped progress counts, and audit events in the caller's transaction.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.review import ReviewStatus
from app.services.review_service import ReviewService, review_service


@pytest.fixture
def service():
    return ReviewService()


@pytest.fixture
def actor_id():
    return uuid.uuid4()


def _make_form_instance() -> FormInstance:
    return FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=FormInstanceStatus.submitted,
        created_at=datetime.now(UTC),
    )


def _mock_session_for_status(status: ReviewStatus | None):
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = status
    session.execute = AsyncMock(return_value=result)
    return session


class TestMarkReviewed:
    async def test_marks_form_reviewed_with_actor_and_timestamp(self, service, actor_id):
        form_instance = _make_form_instance()
        session = _mock_session_for_status(None)

        with patch("app.services.review_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.mark_reviewed(session, form_instance, actor_id)

        assert result.form_instance_id == form_instance.id
        assert result.is_reviewed is True
        assert result.reviewed_by == actor_id
        assert result.reviewed_at is not None
        assert result.reviewed_at.tzinfo is not None
        audit.record.assert_awaited_once()
        audit_kwargs = audit.record.call_args.kwargs
        assert audit_kwargs["entity_type"] == "review_status"
        assert audit_kwargs["action"] == "mark_reviewed"
        assert audit_kwargs["actor_id"] == actor_id
        assert audit_kwargs["old_value"] == "False"
        assert audit_kwargs["new_value"] == "True"

    async def test_marks_existing_status_and_audits_transition(self, service, actor_id):
        form_instance = _make_form_instance()
        existing = ReviewStatus(
            id=uuid.uuid4(),
            form_instance_id=form_instance.id,
            is_reviewed=False,
        )
        session = _mock_session_for_status(existing)

        with patch("app.services.review_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.mark_reviewed(session, form_instance, actor_id)

        assert result is existing
        assert existing.is_reviewed is True
        assert existing.reviewed_by == actor_id
        audit.record.assert_awaited_once()


class TestClearReview:
    async def test_clears_review_and_review_actor_timestamp(self, service, actor_id):
        form_instance = _make_form_instance()
        existing = ReviewStatus(
            id=uuid.uuid4(),
            form_instance_id=form_instance.id,
            is_reviewed=True,
            reviewed_by=uuid.uuid4(),
            reviewed_at=datetime.now(UTC),
        )
        session = _mock_session_for_status(existing)

        with patch("app.services.review_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.clear_review(session, form_instance, actor_id)

        assert result is existing
        assert result.is_reviewed is False
        assert result.reviewed_by is None
        assert result.reviewed_at is None
        assert result.updated_at is not None
        audit.record.assert_awaited_once()
        audit_kwargs = audit.record.call_args.kwargs
        assert audit_kwargs["action"] == "clear_review"
        assert audit_kwargs["actor_id"] == actor_id
        assert audit_kwargs["old_value"] == "True"
        assert audit_kwargs["new_value"] == "False"

    async def test_clear_creates_not_reviewed_baseline_when_missing(
        self, service, actor_id
    ):
        form_instance = _make_form_instance()
        session = _mock_session_for_status(None)

        with patch("app.services.review_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.clear_review(session, form_instance, actor_id)

        assert result.form_instance_id == form_instance.id
        assert result.is_reviewed is False
        assert result.reviewed_by is None
        session.add.assert_called_once_with(result)
        audit.record.assert_awaited_once()


class TestReviewProgress:
    async def test_returns_reviewed_and_not_reviewed_counts(self, service):
        study_id = uuid.uuid4()
        session = AsyncMock()
        row = MagicMock(total=10, reviewed=6)
        result = MagicMock()
        result.one.return_value = row
        session.execute = AsyncMock(return_value=result)

        counts = await service.progress(session, study_id)

        assert counts == {"reviewed": 6, "not_reviewed": 4}
        session.execute.assert_awaited_once()

    async def test_supports_narrower_site_scope(self, service):
        site_id = uuid.uuid4()
        session = AsyncMock()
        row = MagicMock(total=0, reviewed=0)
        result = MagicMock()
        result.one.return_value = row
        session.execute = AsyncMock(return_value=result)

        counts = await service.progress(session, site_id=site_id)

        assert counts == {"reviewed": 0, "not_reviewed": 0}


class TestReviewServiceSingleton:
    def test_singleton_exists(self):
        assert isinstance(review_service, ReviewService)
