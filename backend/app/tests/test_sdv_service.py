"""Unit tests for the SDV service (Requirements 14.1-14.4)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.identity import User, UserStatus
from app.models.sdv import SDVScopeType, SDVStatus
from app.models.subject import Subject, SubjectStatus
from app.services.sdv_service import SDVService, sdv_service


@pytest.fixture
def service():
    return SDVService()


@pytest.fixture
def actor_id():
    return uuid.uuid4()


def _session_for_status(status: SDVStatus | None):
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = status
    session.execute = AsyncMock(return_value=result)
    return session


def _form_instance(subject: Subject) -> FormInstance:
    form = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        visit_instance_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=FormInstanceStatus.in_progress,
        created_at=datetime.now(UTC),
    )
    form.subject = subject
    return form


def _subject() -> Subject:
    return Subject(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        study_version_id=uuid.uuid4(),
        subject_number="101-0001",
        status=SubjectStatus.enrolled,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


class TestSDVToggle:
    async def test_set_sdv_persists_actor_and_timestamp(self, service, actor_id):
        target = _subject()
        session = _session_for_status(None)

        with patch("app.services.sdv_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.set_sdv(session, SDVScopeType.subject, target, actor_id)

        assert result.scope_type == SDVScopeType.subject.value
        assert result.scope_id == target.id
        assert result.is_verified is True
        assert result.verified_by == actor_id
        assert result.verified_at is not None
        session.add.assert_called_once_with(result)
        audit.record.assert_awaited_once()
        assert audit.record.call_args.kwargs["action"] == "set_sdv"
        assert audit.record.call_args.kwargs["entity_type"] == "sdv_status"
        assert audit.record.call_args.kwargs["study_id"] == target.study_id
        assert audit.record.call_args.kwargs["site_id"] == target.site_id
        assert audit.record.call_args.kwargs["subject_id"] == target.id

    async def test_set_sdv_accepts_authenticated_user_object(self, service):
        target = _subject()
        actor = User(
            id=uuid.uuid4(),
            email="cra@example.test",
            first_name="CRA",
            last_name="User",
            status=UserStatus.active,
        )
        session = _session_for_status(None)

        with patch("app.services.sdv_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.set_sdv(session, "subject", target.id, actor)

        assert result.verified_by == actor.id
        assert audit.record.call_args.kwargs["actor_email"] == actor.email

    async def test_clear_sdv_resets_verification_metadata_and_audits(self, service, actor_id):
        target = _subject()
        existing = SDVStatus(
            id=uuid.uuid4(),
            scope_type="subject",
            scope_id=target.id,
            is_verified=True,
            verified_by=uuid.uuid4(),
            verified_at=datetime.now(UTC),
        )
        session = _session_for_status(existing)

        with patch("app.services.sdv_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.clear_sdv(session, SDVScopeType.subject, target, actor_id)

        assert result.is_verified is False
        assert result.verified_by is None
        assert result.verified_at is None
        assert result.updated_at is not None
        audit.record.assert_awaited_once()
        call_kwargs = audit.record.call_args.kwargs
        assert call_kwargs["action"] == "clear_sdv"
        assert call_kwargs["actor_id"] == actor_id
        assert call_kwargs["old_value"] == "True"
        assert call_kwargs["new_value"] == "False"

    async def test_form_scope_uses_loaded_subject_for_audit_context(self, service, actor_id):
        subject = _subject()
        target = _form_instance(subject)
        session = _session_for_status(None)

        with patch("app.services.sdv_service.audit_service") as audit:
            audit.record = AsyncMock()
            await service.set_sdv(session, "form", target, actor_id)

        kwargs = audit.record.call_args.kwargs
        assert kwargs["subject_id"] == subject.id
        assert kwargs["study_id"] == subject.study_id
        assert kwargs["site_id"] == subject.site_id


class TestSDVProgress:
    async def test_progress_returns_verified_and_not_verified_counts(self, service):
        session = AsyncMock()
        result = MagicMock()
        result.one.return_value = MagicMock(total=7, verified=3)
        session.execute = AsyncMock(return_value=result)

        counts = await service.progress(
            session, study_id=uuid.uuid4(), scope_type=SDVScopeType.form
        )

        assert counts == {"verified": 3, "not_verified": 4}
        session.execute.assert_awaited_once()

    async def test_progress_accepts_subject_object_scope(self, service):
        subject = _subject()
        session = AsyncMock()
        result = MagicMock()
        result.one.return_value = MagicMock(total=1, verified=1)
        session.execute = AsyncMock(return_value=result)

        counts = await service.progress(session, subject)

        assert counts == {"verified": 1, "not_verified": 0}


class TestSDVValidation:
    async def test_rejects_mismatched_scope_and_target(self, service, actor_id):
        target = _subject()
        session = AsyncMock()

        with pytest.raises(Exception, match="scope does not match"):
            await service.set_sdv(session, SDVScopeType.form, target, actor_id)

    def test_singleton_exists(self):
        assert isinstance(sdv_service, SDVService)
