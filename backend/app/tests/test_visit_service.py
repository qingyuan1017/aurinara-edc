"""Unit tests for the VisitService.

Validates Requirements:
  - 8.1: define_visit persists the definition on a draft version (and is blocked
          on a published version via guard_mutable).
  - 8.2: initialize_instances creates Visit_Instances from the bound version.
  - 8.3: record_visit_date computes the window status from the visit date.
  - 8.4: create_unscheduled creates an unscheduled Visit_Instance.
  - 8.5: mark_missed sets the Visit_Instance status to missed.
  - Audit: every mutation writes an Audit_Event.
"""

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.edc.study import StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitDefinition, VisitInstance, VisitInstanceStatus
from app.schemas.edc.visit import AddableVisitCreate, UnscheduledVisitCreate, VisitDefinitionCreate
from app.services.edc.visit_service import (
    WINDOW_AFTER,
    WINDOW_BEFORE,
    WINDOW_IN,
    VisitService,
    compute_window_status,
    visit_service,
)


@pytest.fixture
def design_service():
    service = AsyncMock()
    service.permits_unscheduled_visits = AsyncMock(return_value=True)
    return service


@pytest.fixture
def service(design_service):
    return VisitService(design_service=design_service)


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


def _make_definition(
    study_version_id: uuid.UUID | None = None,
    target_day: int | None = 7,
    window_before: int | None = 2,
    window_after: int | None = 2,
    addable: bool = False,
) -> VisitDefinition:
    return VisitDefinition(
        id=uuid.uuid4(),
        study_version_id=study_version_id or uuid.uuid4(),
        name="Visit 1",
        visit_number=1,
        visit_type="scheduled",
        target_day=target_day,
        window_before=window_before,
        window_after=window_after,
        display_order=1,
        is_required=True,
        definition_kind="visit",
        addable=addable,
        created_at=datetime.now(UTC),
    )


def _make_subject() -> Subject:
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


def _make_instance(
    definition: VisitDefinition | None = None,
    status: VisitInstanceStatus = VisitInstanceStatus.scheduled,
    is_user_added: bool = False,
) -> VisitInstance:
    instance = VisitInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        visit_definition_id=definition.id if definition else None,
        name="Visit 1",
        status=status,
        is_user_added=is_user_added,
        created_at=datetime.now(UTC),
    )
    instance.visit_definition = definition
    return instance


# ---------------------------------------------------------------------------
# compute_window_status (pure helper) — Req 8.3
# ---------------------------------------------------------------------------


class TestComputeWindowStatus:
    def test_in_window_at_target(self):
        assert compute_window_status(7, 2, 2, 7) == WINDOW_IN

    def test_in_window_at_lower_bound(self):
        assert compute_window_status(7, 2, 2, 5) == WINDOW_IN

    def test_in_window_at_upper_bound(self):
        assert compute_window_status(7, 2, 2, 9) == WINDOW_IN

    def test_before_window(self):
        assert compute_window_status(7, 2, 2, 4) == WINDOW_BEFORE

    def test_after_window(self):
        assert compute_window_status(7, 2, 2, 10) == WINDOW_AFTER

    def test_none_target_day_returns_none(self):
        assert compute_window_status(None, 2, 2, 5) is None

    def test_none_day_offset_returns_none(self):
        assert compute_window_status(7, 2, 2, None) is None

    def test_none_window_bounds_treated_as_zero(self):
        assert compute_window_status(7, None, None, 7) == WINDOW_IN
        assert compute_window_status(7, None, None, 6) == WINDOW_BEFORE
        assert compute_window_status(7, None, None, 8) == WINDOW_AFTER


# ---------------------------------------------------------------------------
# define_visit — Req 4.2 (delegation)
# ---------------------------------------------------------------------------
#
# Visit *definition* authoring was reassigned to the Designer module
# (``app.services.designer.visit_definition_service``) as part of the
# Designer / EDC refactor. The authoring tests now live in
# ``test_visit_definition_service.py``. ``VisitService.define_visit`` remains a
# thin backward-compatible delegate, verified below.


class TestDefineVisitDelegates:
    async def test_define_visit_delegates_to_designer_service(
        self, service, mock_session, actor_id
    ):
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

        sentinel = object()
        with patch(
            "app.services.edc.visit_service.visit_definition_service.define_visit",
            new=AsyncMock(return_value=sentinel),
        ) as mock_define:
            result = await service.define_visit(mock_session, version, data, actor_id)

        assert result is sentinel
        mock_define.assert_awaited_once_with(mock_session, version, data, actor_id)


# ---------------------------------------------------------------------------
# initialize_instances — Req 8.2
# ---------------------------------------------------------------------------


class TestInitializeInstances:
    async def test_initialize_creates_instances_from_definitions(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        definitions = [
            _make_definition(subject.study_version_id),
            _make_definition(subject.study_version_id),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = definitions
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert len(instances) == 2
        for instance in instances:
            assert instance.subject_id == subject.id
            assert instance.status == VisitInstanceStatus.scheduled
        assert mock_audit.record.await_count == 2
        statement = mock_session.execute.await_args.args[0]
        assert "visit_definitions.addable IS false" in str(statement)

    async def test_initialize_with_no_definitions_returns_empty(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert instances == []
        mock_audit.record.assert_not_awaited()

    async def test_initialize_scopes_to_phase_and_skips_existing_instances(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        existing_definition = _make_definition(subject.study_version_id)
        new_definition = _make_definition(subject.study_version_id)
        definitions_result = MagicMock()
        definitions_result.scalars.return_value.all.return_value = [
            existing_definition,
            new_definition,
        ]
        existing_result = MagicMock()
        existing_result.scalars.return_value.all.return_value = [existing_definition.id]
        mock_session.execute.side_effect = [definitions_result, existing_result]

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(
                mock_session,
                subject,
                actor_id,
                definition_ids={existing_definition.id, new_definition.id},
                skip_existing=True,
            )

        assert [instance.visit_definition_id for instance in instances] == [new_definition.id]
        assert mock_audit.record.await_count == 1

    async def test_initialize_empty_phase_does_not_query_or_create(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()

        instances = await service.initialize_instances(
            mock_session,
            subject,
            actor_id,
            definition_ids=set(),
            skip_existing=True,
        )

        assert instances == []
        mock_session.execute.assert_not_awaited()


class TestAddableVisits:
    async def test_create_addable_uses_real_definition_and_initializes_forms(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        definition = _make_definition(subject.study_version_id)
        definition.addable = True
        definition.definition_kind = "visit"
        result = MagicMock()
        result.scalars.return_value.all.return_value = [definition]
        mock_session.execute = AsyncMock(return_value=result)

        with (
            patch("app.services.edc.visit_service.audit_service") as mock_audit,
            patch("app.services.edc.visit_service.form_instance_service") as mock_forms,
        ):
            mock_audit.record = AsyncMock()
            mock_forms.initialize_for_visit = AsyncMock(return_value=[])
            instance = await service.create_addable(
                mock_session,
                subject,
                AddableVisitCreate(visit_definition_id=definition.id),
                actor_id,
            )

        assert instance.visit_definition_id == definition.id
        assert instance.subject_id == subject.id
        assert instance.status == VisitInstanceStatus.scheduled
        assert instance.is_user_added is True
        mock_forms.initialize_for_visit.assert_awaited_once_with(
            mock_session, subject, instance, actor_id
        )
        assert mock_audit.record.await_args.kwargs["action"] == "create_addable"

    async def test_create_addable_unscheduled_definition_sets_unscheduled_status(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        definition = _make_definition(subject.study_version_id, addable=True)
        definition.visit_type = "unscheduled"
        result = MagicMock()
        result.scalars.return_value.all.return_value = [definition]
        mock_session.execute = AsyncMock(return_value=result)

        with (
            patch("app.services.edc.visit_service.audit_service") as mock_audit,
            patch("app.services.edc.visit_service.form_instance_service") as mock_forms,
        ):
            mock_audit.record = AsyncMock()
            mock_forms.initialize_for_visit = AsyncMock(return_value=[])
            instance = await service.create_addable(
                mock_session,
                subject,
                AddableVisitCreate(visit_definition_id=definition.id),
                actor_id,
                allowed_definition_ids=set(),
            )

        assert instance.status == VisitInstanceStatus.unscheduled

    async def test_create_addable_rejects_non_addable_definition(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=result)

        with pytest.raises(ValidationError, match="not addable"):
            await service.create_addable(
                mock_session,
                subject,
                AddableVisitCreate(visit_definition_id=uuid.uuid4()),
                actor_id,
            )


# ---------------------------------------------------------------------------
# record_visit_date — Req 8.3
# ---------------------------------------------------------------------------


class TestRecordVisitDate:
    async def test_record_in_window(self, service, mock_session, actor_id):
        definition = _make_definition(target_day=7, window_before=2, window_after=2)
        instance = _make_instance(definition)
        baseline = date(2024, 1, 1)
        # day offset 7 -> in window
        visit_date = date(2024, 1, 8)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.record_visit_date(
                mock_session, instance, visit_date, actor_id, baseline_date=baseline
            )

        assert result.visit_date == visit_date
        assert result.window_status == WINDOW_IN
        assert result.status == VisitInstanceStatus.in_window

    async def test_record_before_window(self, service, mock_session, actor_id):
        definition = _make_definition(target_day=7, window_before=2, window_after=2)
        instance = _make_instance(definition)
        baseline = date(2024, 1, 1)
        # day offset 4 -> before window (< 5)
        visit_date = date(2024, 1, 5)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.record_visit_date(
                mock_session, instance, visit_date, actor_id, baseline_date=baseline
            )

        assert result.window_status == WINDOW_BEFORE

    async def test_record_after_window(self, service, mock_session, actor_id):
        definition = _make_definition(target_day=7, window_before=2, window_after=2)
        instance = _make_instance(definition)
        baseline = date(2024, 1, 1)
        # day offset 10 -> after window (> 9)
        visit_date = date(2024, 1, 11)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.record_visit_date(
                mock_session, instance, visit_date, actor_id, baseline_date=baseline
            )

        assert result.window_status == WINDOW_AFTER

    async def test_record_without_baseline_sets_no_window(self, service, mock_session, actor_id):
        definition = _make_definition(target_day=7)
        instance = _make_instance(definition)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.record_visit_date(
                mock_session, instance, date(2024, 1, 8), actor_id
            )

        assert result.visit_date == date(2024, 1, 8)
        assert result.window_status is None

    async def test_record_unscheduled_instance_no_definition(self, service, mock_session, actor_id):
        instance = _make_instance(definition=None)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.record_visit_date(
                mock_session,
                instance,
                date(2024, 1, 8),
                actor_id,
                baseline_date=date(2024, 1, 1),
            )

        assert result.window_status is None

    async def test_record_writes_audit_event(self, service, mock_session, actor_id):
        definition = _make_definition()
        instance = _make_instance(definition)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.record_visit_date(
                mock_session,
                instance,
                date(2024, 1, 8),
                actor_id,
                baseline_date=date(2024, 1, 1),
            )

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "visit_instance"
            assert call_kwargs["action"] == "record_visit_date"
            assert call_kwargs["field_name"] == "visit_date"
            assert call_kwargs["new_value"] == "2024-01-08"


# ---------------------------------------------------------------------------
# create_unscheduled — Req 8.4
# ---------------------------------------------------------------------------


class TestCreateUnscheduled:
    async def test_create_unscheduled_sets_status(self, service, mock_session, actor_id):
        subject = _make_subject()
        data = UnscheduledVisitCreate(name="Unscheduled AE Visit")

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instance = await service.create_unscheduled(mock_session, subject, data, actor_id)

        assert instance.subject_id == subject.id
        assert instance.visit_definition_id is None
        assert instance.name == "Unscheduled AE Visit"
        assert instance.status == VisitInstanceStatus.unscheduled
        assert instance.is_user_added is True

    async def test_create_unscheduled_writes_audit_event(self, service, mock_session, actor_id):
        subject = _make_subject()
        data = UnscheduledVisitCreate(name="Unscheduled Visit", visit_date=date(2024, 2, 1))

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_unscheduled(mock_session, subject, data, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "visit_instance"
            assert call_kwargs["action"] == "create_unscheduled"
            assert call_kwargs["subject_id"] == subject.id

    async def test_create_unscheduled_rejects_design_without_capability(
        self, service, design_service, mock_session, actor_id
    ):
        design_service.permits_unscheduled_visits.return_value = False
        subject = _make_subject()

        with pytest.raises(BusinessRuleError, match="does not permit unscheduled visits"):
            await service.create_unscheduled(
                mock_session,
                subject,
                UnscheduledVisitCreate(name="Unscheduled Visit"),
                actor_id,
            )

        mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# mark_missed — Req 8.5
# ---------------------------------------------------------------------------


class TestMarkMissed:
    async def test_mark_missed_sets_status(self, service, mock_session, actor_id):
        instance = _make_instance(status=VisitInstanceStatus.scheduled)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.mark_missed(mock_session, instance, actor_id)

        assert result.status == VisitInstanceStatus.missed
        assert result.updated_at is not None

    async def test_mark_missed_writes_audit_event(self, service, mock_session, actor_id):
        instance = _make_instance(status=VisitInstanceStatus.scheduled)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.mark_missed(mock_session, instance, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "visit_instance"
            assert call_kwargs["action"] == "mark_missed"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["new_value"] == VisitInstanceStatus.missed.value

    async def test_mark_missed_rejects_added_in_error(self, service, mock_session, actor_id):
        instance = _make_instance(status=VisitInstanceStatus.added_in_error, is_user_added=True)

        with pytest.raises(BusinessRuleError, match="cannot be modified"):
            await service.mark_missed(mock_session, instance, actor_id)


class TestMarkAddedInError:
    async def test_marks_empty_user_added_visit_and_audits_reason(
        self, service, mock_session, actor_id
    ):
        instance = _make_instance(is_user_added=True)
        service._has_clinical_data = AsyncMock(return_value=False)

        with patch("app.services.edc.visit_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.mark_added_in_error(
                mock_session, instance, actor_id, "Created for the wrong subject"
            )

        assert result.status == VisitInstanceStatus.added_in_error
        call_kwargs = mock_audit.record.call_args.kwargs
        assert call_kwargs["action"] == "mark_added_in_error"
        assert call_kwargs["old_value"] == VisitInstanceStatus.scheduled.value
        assert call_kwargs["new_value"] == VisitInstanceStatus.added_in_error.value
        assert call_kwargs["reason"] == "Created for the wrong subject"

    async def test_rejects_protocol_generated_visit(self, service, mock_session, actor_id):
        instance = _make_instance(is_user_added=False)

        with pytest.raises(BusinessRuleError, match="Only a user-added visit"):
            await service.mark_added_in_error(mock_session, instance, actor_id, "Wrong visit")

    async def test_rejects_visit_with_clinical_data(self, service, mock_session, actor_id):
        instance = _make_instance(is_user_added=True)
        service._has_clinical_data = AsyncMock(return_value=True)

        with pytest.raises(BusinessRuleError, match="after clinical data entry"):
            await service.mark_added_in_error(mock_session, instance, actor_id, "Wrong visit")

        assert instance.status == VisitInstanceStatus.scheduled

    async def test_rejects_blank_reason(self, service, mock_session, actor_id):
        instance = _make_instance(is_user_added=True)

        with pytest.raises(ValidationError, match="Reason is required"):
            await service.mark_added_in_error(mock_session, instance, actor_id, "   ")


# ---------------------------------------------------------------------------
# get_instance
# ---------------------------------------------------------------------------


class TestGetInstance:
    async def test_get_instance_returns_instance(self, service, mock_session):
        expected = _make_instance()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_instance(mock_session, expected.id)
        assert result == expected

    async def test_get_instance_raises_not_found(self, service, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_instance(mock_session, uuid.uuid4())


class TestVisitServiceSingleton:
    def test_singleton_exists(self):
        assert visit_service is not None
        assert isinstance(visit_service, VisitService)
