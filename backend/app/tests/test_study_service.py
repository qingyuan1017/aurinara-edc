"""Unit tests for the StudyService.

Validates Requirements:
  - 4.1: create_study persists study metadata with status Draft.
  - 4.2: create_study rejects duplicate study codes (ConflictError).
  - 4.3: transition_status enforces legal state machine transitions.
  - 4.5: create_study and transition_status write Audit_Events.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.schemas.study import StudyCreate
from app.services.study_service import StudyService, study_service


@pytest.fixture
def service():
    """Fresh StudyService instance for each test."""
    return StudyService()


@pytest.fixture
def mock_session():
    """Mock AsyncSession that tracks add/flush calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def study_create_data():
    """Valid StudyCreate schema."""
    return StudyCreate(
        study_code="STUDY-001",
        protocol_number="PROT-2024-001",
        title="Phase III Cardiovascular Trial",
        sponsor="PharmaCorp",
        phase="Phase III",
        therapeutic_area="Cardiology",
        indication="Hypertension",
    )


@pytest.fixture
def actor_id():
    """Actor UUID for audit purposes."""
    return uuid.uuid4()


def _make_study(status: StudyStatus = StudyStatus.draft) -> Study:
    """Create a Study instance for testing."""
    study = Study(
        id=uuid.uuid4(),
        study_code="STUDY-001",
        title="Test Study",
        status=status,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    return study


class TestCreateStudy:
    """Tests for StudyService.create_study()."""

    async def test_create_study_checks_uniqueness(self, service, mock_session, study_create_data, actor_id):
        """create_study raises ConflictError when study_code already exists (Req 4.2)."""
        # Mock: existing study found
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = _make_study()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ConflictError) as exc_info:
            await service.create_study(mock_session, study_create_data, actor_id)

        assert "already exists" in exc_info.value.message
        assert exc_info.value.details["study_code"] == "STUDY-001"

    async def test_create_study_persists_metadata(self, service, mock_session, study_create_data, actor_id):
        """create_study creates a Study with correct metadata and Draft status (Req 4.1)."""
        # Mock: no existing study
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.study_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            study = await service.create_study(mock_session, study_create_data, actor_id)

        assert study.study_code == "STUDY-001"
        assert study.protocol_number == "PROT-2024-001"
        assert study.title == "Phase III Cardiovascular Trial"
        assert study.sponsor == "PharmaCorp"
        assert study.phase == "Phase III"
        assert study.therapeutic_area == "Cardiology"
        assert study.indication == "Hypertension"
        assert study.status == StudyStatus.draft
        assert study.created_by == actor_id

    async def test_create_study_creates_initial_version(self, service, mock_session, study_create_data, actor_id):
        """create_study also creates an initial StudyVersion 1.0 in draft status."""
        # Mock: no existing study
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.study_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_study(mock_session, study_create_data, actor_id)

        # session.add should be called twice: once for study, once for version
        assert mock_session.add.call_count == 2
        # Check the second add call is a StudyVersion
        version_call = mock_session.add.call_args_list[1]
        version = version_call[0][0]
        assert isinstance(version, StudyVersion)
        assert version.version_number == "1.0"
        assert version.status == StudyVersionStatus.draft

    async def test_create_study_writes_audit_event(self, service, mock_session, study_create_data, actor_id):
        """create_study writes an Audit_Event (Req 4.5)."""
        # Mock: no existing study
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.study_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_study(mock_session, study_create_data, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "study"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["actor_id"] == actor_id


class TestTransitionStatus:
    """Tests for StudyService.transition_status()."""

    @pytest.mark.parametrize(
        "current,target",
        [
            (StudyStatus.draft, StudyStatus.uat),
            (StudyStatus.uat, StudyStatus.active),
            (StudyStatus.active, StudyStatus.enrollment_closed),
            (StudyStatus.enrollment_closed, StudyStatus.locked),
            (StudyStatus.locked, StudyStatus.archived),
        ],
    )
    async def test_legal_transitions_succeed(self, service, mock_session, actor_id, current, target):
        """All legal transitions in the state machine succeed (Req 4.3)."""
        study = _make_study(status=current)

        with patch("app.services.study_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.transition_status(mock_session, study, target, actor_id)

        assert result.status == target
        assert result.updated_at is not None

    @pytest.mark.parametrize(
        "current,target",
        [
            (StudyStatus.draft, StudyStatus.active),  # skip UAT
            (StudyStatus.draft, StudyStatus.locked),
            (StudyStatus.uat, StudyStatus.draft),  # backwards
            (StudyStatus.active, StudyStatus.uat),  # backwards
            (StudyStatus.active, StudyStatus.archived),  # skip steps
            (StudyStatus.archived, StudyStatus.draft),  # terminal state
            (StudyStatus.archived, StudyStatus.active),
        ],
    )
    async def test_illegal_transitions_raise_business_rule_error(
        self, service, mock_session, actor_id, current, target
    ):
        """Illegal transitions raise BusinessRuleError (Req 4.3)."""
        study = _make_study(status=current)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.transition_status(mock_session, study, target, actor_id)

        assert "Illegal status transition" in exc_info.value.message
        assert exc_info.value.details["current_status"] == current.value
        assert exc_info.value.details["target_status"] == target.value

    async def test_transition_writes_audit_event(self, service, mock_session, actor_id):
        """transition_status writes an Audit_Event with old and new status (Req 4.5)."""
        study = _make_study(status=StudyStatus.draft)

        with patch("app.services.study_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.transition_status(mock_session, study, StudyStatus.uat, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "study"
            assert call_kwargs["action"] == "status_transition"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == "Draft"
            assert call_kwargs["new_value"] == "UAT"
            assert call_kwargs["actor_id"] == actor_id

    async def test_transition_from_same_status_raises_error(self, service, mock_session, actor_id):
        """Transitioning to the same status is not allowed."""
        study = _make_study(status=StudyStatus.active)

        with pytest.raises(BusinessRuleError):
            await service.transition_status(mock_session, study, StudyStatus.active, actor_id)


class TestGetStudy:
    """Tests for StudyService.get_study()."""

    async def test_get_study_returns_study(self, service, mock_session):
        """get_study returns the study when found."""
        expected_study = _make_study()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected_study
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_study(mock_session, expected_study.id)
        assert result == expected_study

    async def test_get_study_raises_not_found(self, service, mock_session):
        """get_study raises NotFoundError when no study exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_study(mock_session, uuid.uuid4())

        assert "not found" in exc_info.value.message


class TestListStudies:
    """Tests for StudyService.list_studies()."""

    async def test_list_studies_returns_paginated_response(self, service):
        """list_studies returns a PaginatedResponse."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        from app.api.deps import PaginationParams

        pagination = PaginationParams(page=1, page_size=25)
        result = await service.list_studies(mock_session, pagination)

        assert result.page == 1
        assert result.page_size == 25
        assert result.total == 0
        assert result.items == []


class TestStudyServiceSingleton:
    """Tests for the module-level singleton."""

    def test_singleton_exists(self):
        """The module exports a singleton study_service instance."""
        assert study_service is not None
        assert isinstance(study_service, StudyService)
