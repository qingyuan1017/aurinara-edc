"""Unit tests for the SubjectService.

Validates Requirements:
  - 7.1: create_subject persists metadata and binds to the published version.
  - 7.2: create_subject generates the subject id by rule and enforces uniqueness.
  - 7.3: transition_status enforces the subject state machine.
  - 7.5: get_casebook returns the visit/form structure with clinical status.
  - 7.6: status changes write Audit_Events.
  - 22.2: soft_delete retains the record (deleted_at/by/reason set).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
)
from app.models.site import Site, SiteStatus
from app.models.study import StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.schemas.subject import SubjectCreate
from app.services.subject_service import SubjectService, subject_service


@pytest.fixture
def service():
    """Fresh SubjectService instance for each test."""
    return SubjectService()


@pytest.fixture
def mock_session():
    """Mock AsyncSession that tracks add/flush calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def actor_id():
    return uuid.uuid4()


@pytest.fixture
def study_id():
    return uuid.uuid4()


@pytest.fixture
def site_id():
    return uuid.uuid4()


def _make_site(site_id: uuid.UUID, study_id: uuid.UUID) -> Site:
    return Site(
        id=site_id,
        study_id=study_id,
        site_number="101",
        name="Test Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )


def _make_version(study_id: uuid.UUID) -> StudyVersion:
    return StudyVersion(
        id=uuid.uuid4(),
        study_id=study_id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


def _make_subject(
    study_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status: SubjectStatus = SubjectStatus.screening,
) -> Subject:
    return Subject(
        id=uuid.uuid4(),
        study_id=study_id or uuid.uuid4(),
        site_id=site_id or uuid.uuid4(),
        study_version_id=uuid.uuid4(),
        subject_number="101-0001",
        status=status,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


def _execute_side_effect(*results):
    """Build an AsyncMock.execute side_effect returning the given mock results in order."""
    mocks = []
    for r in results:
        m = MagicMock()
        if isinstance(r, tuple):
            kind, value = r
            if kind == "first":
                m.scalars.return_value.first.return_value = value
            elif kind == "count":
                m.scalar_one.return_value = value
        mocks.append(m)
    return mocks


class TestCreateSubject:
    """Tests for SubjectService.create_subject()."""

    async def test_create_subject_binds_published_version_and_generates_id(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """create_subject binds the published version and generates the id (Req 7.1, 7.2)."""
        site = _make_site(site_id, study_id)
        version = _make_version(study_id)

        # execute call order: site lookup, published version, count for id gen, uniqueness
        results = _execute_side_effect(
            ("first", site),  # site lookup
            ("first", version),  # published version
            ("count", 0),  # sequence count
            ("first", None),  # uniqueness check
        )
        mock_session.execute = AsyncMock(side_effect=results)

        data = SubjectCreate(site_id=site_id)

        with (
            patch("app.services.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.visit_service.visit_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ) as mock_init,
        ):
            mock_audit.record = AsyncMock()
            subject = await service.create_subject(
                mock_session, study_id, data, actor_id
            )

        assert subject.study_id == study_id
        assert subject.site_id == site_id
        assert subject.study_version_id == version.id
        assert subject.status == SubjectStatus.screening
        assert subject.created_by == actor_id
        # Generated id follows {site_number}-{sequence}
        assert subject.subject_number == "101-0001"
        # Visit_Instances are initialized from the bound version (Req 7.4, 8.2)
        mock_init.assert_awaited_once_with(mock_session, subject, actor_id)

    async def test_create_subject_uses_provided_number(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """create_subject uses an explicitly provided subject_number."""
        site = _make_site(site_id, study_id)
        version = _make_version(study_id)

        results = _execute_side_effect(
            ("first", site),  # site lookup
            ("first", version),  # published version
            ("first", None),  # uniqueness check (no count since number provided)
        )
        mock_session.execute = AsyncMock(side_effect=results)

        data = SubjectCreate(site_id=site_id, subject_number="CUSTOM-007")

        with (
            patch("app.services.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.visit_service.visit_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ),
        ):
            mock_audit.record = AsyncMock()
            subject = await service.create_subject(
                mock_session, study_id, data, actor_id
            )

        assert subject.subject_number == "CUSTOM-007"

    async def test_create_subject_no_site_raises_not_found(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """create_subject raises NotFoundError when the site is missing."""
        results = _execute_side_effect(("first", None))
        mock_session.execute = AsyncMock(side_effect=results)

        data = SubjectCreate(site_id=site_id)

        with pytest.raises(NotFoundError):
            await service.create_subject(mock_session, study_id, data, actor_id)

    async def test_create_subject_no_published_version_raises_business_rule(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """create_subject raises BusinessRuleError when no published version exists (Req 7.1)."""
        site = _make_site(site_id, study_id)
        results = _execute_side_effect(
            ("first", site),  # site lookup
            ("first", None),  # no published version
        )
        mock_session.execute = AsyncMock(side_effect=results)

        data = SubjectCreate(site_id=site_id)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.create_subject(mock_session, study_id, data, actor_id)

        assert "published version" in exc_info.value.message

    async def test_create_subject_duplicate_number_raises_conflict(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """create_subject raises ConflictError on duplicate subject_number (Req 7.2)."""
        site = _make_site(site_id, study_id)
        version = _make_version(study_id)
        results = _execute_side_effect(
            ("first", site),  # site lookup
            ("first", version),  # published version
            ("first", _make_subject(study_id, site_id)),  # uniqueness check finds dup
        )
        mock_session.execute = AsyncMock(side_effect=results)

        data = SubjectCreate(site_id=site_id, subject_number="101-0001")

        with pytest.raises(ConflictError) as exc_info:
            await service.create_subject(mock_session, study_id, data, actor_id)

        assert "already exists" in exc_info.value.message

    async def test_create_subject_writes_audit_event(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """create_subject writes an Audit_Event (Req 7.6 / single tx)."""
        site = _make_site(site_id, study_id)
        version = _make_version(study_id)
        results = _execute_side_effect(
            ("first", site),
            ("first", version),
            ("count", 0),
            ("first", None),
        )
        mock_session.execute = AsyncMock(side_effect=results)

        data = SubjectCreate(site_id=site_id)

        with (
            patch("app.services.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.visit_service.visit_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ),
        ):
            mock_audit.record = AsyncMock()
            await service.create_subject(mock_session, study_id, data, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "subject"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["actor_id"] == actor_id
            assert call_kwargs["study_id"] == study_id


class TestTransitionStatus:
    """Tests for SubjectService.transition_status()."""

    @pytest.mark.parametrize(
        "current,target",
        [
            (SubjectStatus.screening, SubjectStatus.screen_failed),
            (SubjectStatus.screening, SubjectStatus.enrolled),
            (SubjectStatus.enrolled, SubjectStatus.randomized),
            (SubjectStatus.enrolled, SubjectStatus.withdrawn),
            (SubjectStatus.enrolled, SubjectStatus.early_terminated),
            (SubjectStatus.randomized, SubjectStatus.on_treatment),
            (SubjectStatus.on_treatment, SubjectStatus.completed),
            (SubjectStatus.on_treatment, SubjectStatus.early_terminated),
            (SubjectStatus.on_treatment, SubjectStatus.lost_to_follow_up),
            (SubjectStatus.on_treatment, SubjectStatus.withdrawn),
        ],
    )
    async def test_legal_transitions_succeed(
        self, service, mock_session, actor_id, current, target
    ):
        """All legal subject transitions succeed (Req 7.3)."""
        subject = _make_subject(status=current)

        with patch("app.services.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.transition_status(
                mock_session, subject, target, actor_id
            )

        assert result.status == target
        assert result.updated_at is not None

    @pytest.mark.parametrize(
        "current,target",
        [
            (SubjectStatus.screening, SubjectStatus.randomized),  # skip enrolled
            (SubjectStatus.screening, SubjectStatus.on_treatment),
            (SubjectStatus.enrolled, SubjectStatus.on_treatment),  # skip randomized
            (SubjectStatus.randomized, SubjectStatus.completed),  # skip on treatment
            (SubjectStatus.screen_failed, SubjectStatus.enrolled),  # terminal
            (SubjectStatus.completed, SubjectStatus.on_treatment),  # terminal
            (SubjectStatus.withdrawn, SubjectStatus.enrolled),  # terminal
            (SubjectStatus.enrolled, SubjectStatus.screening),  # backwards
        ],
    )
    async def test_illegal_transitions_raise_business_rule_error(
        self, service, mock_session, actor_id, current, target
    ):
        """Illegal subject transitions raise BusinessRuleError (Req 7.3)."""
        subject = _make_subject(status=current)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.transition_status(mock_session, subject, target, actor_id)

        assert "Illegal subject status transition" in exc_info.value.message
        assert exc_info.value.details["current_status"] == current.value
        assert exc_info.value.details["target_status"] == target.value

    async def test_transition_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """transition_status writes an Audit_Event with old/new status (Req 7.6)."""
        subject = _make_subject(status=SubjectStatus.screening)

        with patch("app.services.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.transition_status(
                mock_session, subject, SubjectStatus.enrolled, actor_id
            )

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "subject"
            assert call_kwargs["action"] == "status_transition"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == "Screening"
            assert call_kwargs["new_value"] == "Enrolled"
            assert call_kwargs["actor_id"] == actor_id

    async def test_transition_to_same_status_raises_error(
        self, service, mock_session, actor_id
    ):
        """Transitioning to the same status is not allowed."""
        subject = _make_subject(status=SubjectStatus.enrolled)

        with pytest.raises(BusinessRuleError):
            await service.transition_status(
                mock_session, subject, SubjectStatus.enrolled, actor_id
            )


class TestGetCasebook:
    """Tests for SubjectService.get_casebook()."""

    async def test_get_casebook_returns_structure(self, service, mock_session):
        """get_casebook returns the subject envelope with clinical status (Req 7.5)."""
        subject = _make_subject(status=SubjectStatus.enrolled)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = subject
        mock_session.execute = AsyncMock(return_value=mock_result)

        casebook = await service.get_casebook(mock_session, subject.id)

        assert casebook["subject_id"] == subject.id
        assert casebook["subject_number"] == subject.subject_number
        assert casebook["status"] == SubjectStatus.enrolled
        assert casebook["study_version_id"] == subject.study_version_id
        assert casebook["visits"] == []

    async def test_get_casebook_missing_subject_raises_not_found(
        self, service, mock_session
    ):
        """get_casebook raises NotFoundError for a missing subject."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_casebook(mock_session, uuid.uuid4())


class TestSoftDelete:
    """Tests for SubjectService.soft_delete()."""

    async def test_soft_delete_sets_deletion_fields(
        self, service, mock_session, actor_id
    ):
        """soft_delete sets deleted_at/by/reason and retains the record (Req 22.2)."""
        subject = _make_subject()

        with patch("app.services.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.soft_delete(
                mock_session, subject, "entered in error", actor_id
            )

        assert result.deleted_at is not None
        assert result.deleted_by == actor_id
        assert result.deletion_reason == "entered in error"

    async def test_soft_delete_already_deleted_raises_conflict(
        self, service, mock_session, actor_id
    ):
        """soft_delete raises ConflictError if already deleted."""
        subject = _make_subject()
        subject.deleted_at = datetime.now(UTC)

        with pytest.raises(ConflictError):
            await service.soft_delete(mock_session, subject, "reason", actor_id)

    async def test_soft_delete_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """soft_delete writes an Audit_Event with the reason."""
        subject = _make_subject()

        with patch("app.services.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.soft_delete(mock_session, subject, "duplicate", actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "subject"
            assert call_kwargs["action"] == "delete"
            assert call_kwargs["reason"] == "duplicate"
            assert call_kwargs["actor_id"] == actor_id


class TestGetSubject:
    """Tests for SubjectService.get_subject()."""

    async def test_get_subject_returns_subject(self, service, mock_session):
        expected = _make_subject()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_subject(mock_session, expected.id)
        assert result == expected

    async def test_get_subject_raises_not_found(self, service, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_subject(mock_session, uuid.uuid4())


class TestListSubjects:
    """Tests for SubjectService.list_subjects()."""

    async def test_list_subjects_returns_paginated_response(self, service, study_id):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        from app.api.deps import PaginationParams

        pagination = PaginationParams(page=1, page_size=25)
        result = await service.list_subjects(mock_session, study_id, pagination)

        assert result.page == 1
        assert result.page_size == 25
        assert result.total == 0
        assert result.items == []


class TestSubjectServiceSingleton:
    def test_singleton_exists(self):
        assert subject_service is not None
        assert isinstance(subject_service, SubjectService)
