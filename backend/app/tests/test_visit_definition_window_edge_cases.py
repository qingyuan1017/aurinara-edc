"""Edge-case tests for Visit_Definition window ordering (Designer module).

Focused boundary coverage for the visit-window ordering rule authored by
``VisitDefinitionService.define_visit`` and its ``_validate_window`` helper.
These complement the broader behavior in ``test_visit_definition_service.py``
by pinning the window-ordering boundaries called out by task 4.4.

Validates Requirements:
  - 4.2: A Visit_Definition with window bounds where the lower edge is no later
          than the upper edge is persisted. This includes equality (lower edge
          == upper edge) and open-sided windows (one bound ``None``).
  - 4.3: A Visit_Definition whose lower window bound exceeds its upper window
          bound is rejected with a ``ValidationError`` that identifies the
          window (visit_name, visit_number, window_before, window_after), and
          nothing is persisted.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ValidationError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.schemas.designer.visit import VisitDefinitionCreate
from app.services.designer.visit_definition_service import VisitDefinitionService


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


def _draft_version() -> StudyVersion:
    return StudyVersion(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        version_number="1.0",
        status=StudyVersionStatus.draft,
        created_at=datetime.now(UTC),
    )


def _window(window_before: int | None, window_after: int | None) -> MagicMock:
    """Build a window-ordering payload stand-in for ``_validate_window``.

    Uses a ``MagicMock`` so negative offsets (an inverted lower edge) can be
    exercised directly; the schema itself forbids negative bounds, so the
    service guard is the only place inversion can be constructed and tested.
    """
    data = MagicMock()
    data.name = "Window Visit"
    data.visit_number = 7
    data.window_before = window_before
    data.window_after = window_after
    return data


async def _define(service, mock_session, actor_id, data: VisitDefinitionCreate):
    with patch(
        "app.services.designer.visit_definition_service.audit_service"
    ) as mock_audit:
        mock_audit.record = AsyncMock()
        return await service.define_visit(
            mock_session, _draft_version(), data, actor_id
        )


# ---------------------------------------------------------------------------
# Window ordering at equality — accepted (R4.2)
# ---------------------------------------------------------------------------
class TestEqualityBoundary:
    def test_validate_window_accepts_zero_width_window(self, service):
        # lower edge (-0) == upper edge (0): the narrowest possible window.
        service._validate_window(_window(0, 0))  # must not raise

    def test_validate_window_accepts_lower_edge_equal_to_upper_edge(self, service):
        # Craft an exact equality of the edges: lower_edge == upper_edge == 5.
        # lower_edge = -window_before, so window_before = -5 and window_after = 5.
        service._validate_window(_window(-5, 5))  # must not raise

    async def test_define_visit_persists_zero_width_window(
        self, service, mock_session, actor_id
    ):
        data = VisitDefinitionCreate(
            name="Baseline",
            visit_number=1,
            visit_type="scheduled",
            target_day=0,
            window_before=0,
            window_after=0,
            display_order=1,
        )

        definition = await _define(service, mock_session, actor_id, data)

        assert definition.window_before == 0
        assert definition.window_after == 0
        mock_session.add.assert_called_once()


# ---------------------------------------------------------------------------
# Window inversion — rejected, nothing persisted (R4.3)
# ---------------------------------------------------------------------------
class TestInversion:
    def test_validate_window_rejects_single_step_inversion(self, service):
        # Smallest inversion: lower_edge (+1) just past upper_edge (0).
        with pytest.raises(ValidationError) as exc_info:
            service._validate_window(_window(-1, 0))

        details = exc_info.value.details
        assert details["visit_name"] == "Window Visit"
        assert details["visit_number"] == 7
        assert details["window_before"] == -1
        assert details["window_after"] == 0

    def test_validate_window_error_identifies_window(self, service):
        with pytest.raises(ValidationError) as exc_info:
            service._validate_window(_window(-8, 3))

        details = exc_info.value.details
        # The error names the window so the designer can locate the problem.
        assert set(details) >= {
            "visit_name",
            "visit_number",
            "window_before",
            "window_after",
        }
        assert details["window_before"] == -8
        assert details["window_after"] == 3

    async def test_define_visit_persists_nothing_on_inverted_window(
        self, service, mock_session, actor_id
    ):
        # Bypass the schema's non-negative bound so define_visit sees an
        # inverted window and must reject it before touching the session.
        data = MagicMock()
        data.name = "Inverted"
        data.visit_number = 2
        data.visit_type = "scheduled"
        data.target_day = 10
        data.window_before = -4  # lower edge = +4
        data.window_after = 1  # upper edge = +1  -> inverted
        data.display_order = 1
        data.is_required = True

        with pytest.raises(ValidationError):
            await _define(service, mock_session, actor_id, data)

        mock_session.add.assert_not_called()
        mock_session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# Open-sided windows (one bound None) — accepted (R4.2)
# ---------------------------------------------------------------------------
class TestOpenSidedWindows:
    def test_validate_window_accepts_open_lower(self, service):
        service._validate_window(_window(None, 5))  # must not raise

    def test_validate_window_accepts_open_upper(self, service):
        service._validate_window(_window(5, None))  # must not raise

    def test_validate_window_accepts_both_open(self, service):
        service._validate_window(_window(None, None))  # must not raise

    async def test_define_visit_persists_open_sided_window(
        self, service, mock_session, actor_id
    ):
        data = VisitDefinitionCreate(
            name="Open window",
            visit_number=3,
            visit_type="unscheduled",
            target_day=None,
            window_before=None,
            window_after=7,
            display_order=1,
        )

        definition = await _define(service, mock_session, actor_id, data)

        assert definition.window_before is None
        assert definition.window_after == 7
        mock_session.add.assert_called_once()
