"""Unit tests for the Designer-owned VisitDefinitionService.

Visit *definition* authoring was reassigned from the EDC ``visit_service`` to
the Designer module as part of the Designer / EDC refactor. These tests cover
the authoring behavior at its new home.

Validates Requirements:
  - 2.4: define_visit is blocked on a published version (via guard_mutable).
  - 4.2: define_visit persists a Visit_Definition on a draft Design_Version.
  - 4.3: define_visit rejects an inverted window (lower > upper) with an error
          that identifies the invalid window, and persists nothing.
  - Audit: the authoring mutation writes an Audit_Event.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, ValidationError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.schemas.designer.visit import VisitDefinitionCreate
from app.services.designer.visit_definition_service import (
    VisitDefinitionService,
    visit_definition_service,
)


@pytest.fixture
def service():
    return VisitDefinitionService()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def actor_id():
    return uuid.uuid4()


def _make_version(
    status: StudyVersionStatus = StudyVersionStatus.draft,
) -> StudyVersion:
    return StudyVersion(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        version_number="1.0",
        status=status,
        created_at=datetime.now(UTC),
    )


class TestDefineVisit:
    async def test_define_visit_persists_definition(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        data = VisitDefinitionCreate(
            name="Screening",
            visit_number=1,
            visit_type="screening",
            target_day=0,
            window_before=0,
            window_after=3,
            display_order=1,
            is_required=True,
        )

        with patch("app.services.designer.visit_definition_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            definition = await service.define_visit(mock_session, version, data, actor_id)

        assert definition.study_version_id == version.id
        assert definition.name == "Screening"
        assert definition.visit_number == 1
        assert definition.visit_type == "screening"
        assert definition.target_day == 0
        assert definition.window_after == 3
        assert definition.display_order == 1
        assert definition.is_required is True
        assert definition.addable is False
        mock_session.add.assert_called_once()

    async def test_define_visit_persists_addable_for_real_visit(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        data = VisitDefinitionCreate(
            name="Optional follow-up",
            visit_number=2,
            visit_type="unscheduled",
            display_order=2,
            addable=True,
        )

        with patch("app.services.designer.visit_definition_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            definition = await service.define_visit(mock_session, version, data, actor_id)

        assert definition.definition_kind == "visit"
        assert definition.addable is True

    @pytest.mark.parametrize("definition_kind", ["folder", "cycle"])
    def test_container_cannot_be_addable(self, definition_kind):
        with pytest.raises(ValueError, match="Only a visit can be addable"):
            VisitDefinitionCreate(
                name="Container",
                definition_kind=definition_kind,
                visit_type="cycle" if definition_kind == "cycle" else "common",
                display_order=1,
                addable=True,
            )

    async def test_define_visit_blocked_on_published_version(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.published)
        data = VisitDefinitionCreate(
            name="Visit 1",
            visit_number=1,
            visit_type="scheduled",
            display_order=1,
        )

        with pytest.raises(BusinessRuleError):
            await service.define_visit(mock_session, version, data, actor_id)

        mock_session.add.assert_not_called()

    async def test_define_visit_writes_audit_event(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        data = VisitDefinitionCreate(
            name="Visit 1",
            visit_number=1,
            visit_type="scheduled",
            display_order=1,
        )

        with patch("app.services.designer.visit_definition_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.define_visit(mock_session, version, data, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "visit_definition"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["actor_id"] == actor_id
            assert call_kwargs["study_id"] == version.study_id


class TestWindowValidation:
    """Requirement 4.3 — reject an inverted window, identifying it in the error."""

    async def test_equal_window_bounds_are_accepted(self, service, mock_session, actor_id):
        # lower edge == upper edge at the target day (both bounds zero).
        version = _make_version(StudyVersionStatus.draft)
        data = VisitDefinitionCreate(
            name="Baseline",
            visit_number=1,
            visit_type="scheduled",
            target_day=10,
            window_before=0,
            window_after=0,
            display_order=1,
        )

        with patch("app.services.designer.visit_definition_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            definition = await service.define_visit(mock_session, version, data, actor_id)

        assert definition.window_before == 0
        assert definition.window_after == 0

    async def test_valid_window_with_positive_bounds_is_accepted(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        data = VisitDefinitionCreate(
            name="Week 4",
            visit_number=2,
            visit_type="scheduled",
            target_day=28,
            window_before=3,
            window_after=5,
            display_order=2,
        )

        with patch("app.services.designer.visit_definition_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            definition = await service.define_visit(mock_session, version, data, actor_id)

        assert definition.window_before == 3
        assert definition.window_after == 5

    async def test_validate_window_rejects_inverted_window(self, service):
        # Construct a payload whose lower edge (-window_before) exceeds the upper
        # edge (window_after). With non-negative schema bounds this requires a
        # negative lower offset, so exercise the guard directly with a crafted
        # object that bypasses the schema validator.
        bad = MagicMock()
        bad.name = "Bad window"
        bad.visit_number = 3
        bad.window_before = -5  # lower edge = +5
        bad.window_after = 2  # upper edge = +2  -> inverted

        with pytest.raises(ValidationError) as exc_info:
            service._validate_window(bad)

        details = exc_info.value.details
        assert details["visit_name"] == "Bad window"
        assert details["visit_number"] == 3
        assert details["window_before"] == -5
        assert details["window_after"] == 2

    async def test_validate_window_allows_open_sided_windows(self, service):
        # A missing bound leaves that side open and cannot be inverted.
        one_sided = MagicMock()
        one_sided.name = "Open"
        one_sided.visit_number = 1
        one_sided.window_before = None
        one_sided.window_after = 3
        service._validate_window(one_sided)  # must not raise


def test_singleton_exists():
    assert isinstance(visit_definition_service, VisitDefinitionService)
