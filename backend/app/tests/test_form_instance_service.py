"""Unit tests for the FormInstanceService.

Validates Requirements:
  - 7.4: When a Subject is created, Form_Instances are initialized only for
          form/visit pairs in the bound published schedule of assessment.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.edc.form_data import FormInstanceStatus
from app.models.edc.form_metadata import FormDefinition
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.services.edc.form_instance_service import FormInstanceService, form_instance_service


@pytest.fixture
def design_service():
    service = MagicMock()
    service.get_schedule_of_assessment = AsyncMock(return_value=SimpleNamespace(entries=()))
    return service


@pytest.fixture
def service(design_service):
    """Fresh FormInstanceService instance for each test."""
    return FormInstanceService(design_service=design_service)


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
def study_version_id():
    return uuid.uuid4()


def _make_subject(study_version_id: uuid.UUID) -> Subject:
    return Subject(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        study_version_id=study_version_id,
        subject_number="101-0001",
        status=SubjectStatus.screening,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


def _make_visit_instance(subject_id: uuid.UUID, name: str = "Visit 1") -> VisitInstance:
    return VisitInstance(
        id=uuid.uuid4(),
        subject_id=subject_id,
        visit_definition_id=uuid.uuid4(),
        name=name,
        status=VisitInstanceStatus.scheduled,
        created_at=datetime.now(UTC),
    )


def _make_form_definition(
    study_version_id: uuid.UUID,
    form_code: str = "DM",
    display_order: int = 0,
    is_repeating: bool = False,
) -> FormDefinition:
    return FormDefinition(
        id=uuid.uuid4(),
        study_version_id=study_version_id,
        name=f"Form {form_code}",
        form_code=form_code,
        display_order=display_order,
        is_repeating=is_repeating,
        created_at=datetime.now(UTC),
    )


def _schedule(*entries: tuple[uuid.UUID | None, uuid.UUID | None]):
    return SimpleNamespace(
        entries=tuple(
            SimpleNamespace(
                visit_definition_id=visit_definition_id,
                form_definition_id=form_definition_id,
            )
            for visit_definition_id, form_definition_id in entries
        )
    )


class TestInitializeInstances:
    """Tests for FormInstanceService.initialize_instances()."""

    async def test_creates_only_form_instances_scheduled_for_each_visit(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        """Unchecked SoA cells do not create operational form instances."""
        subject = _make_subject(study_version_id)
        visit1 = _make_visit_instance(subject.id, "Screening")
        visit2 = _make_visit_instance(subject.id, "Baseline")
        form_dm = _make_form_definition(study_version_id, "DM", 0)
        form_ae = _make_form_definition(study_version_id, "AE", 1, is_repeating=True)
        design_service.get_schedule_of_assessment.return_value = _schedule(
            (visit1.visit_definition_id, form_dm.id),
            (visit2.visit_definition_id, form_ae.id),
        )

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit1, visit2]
        mock_session.execute = AsyncMock(return_value=visit_result)

        with patch("app.services.edc.form_instance_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert len(instances) == 2
        assert mock_session.add.call_count == 2

        # All have status "Not Started"
        for inst in instances:
            assert inst.status == FormInstanceStatus.not_started
            assert inst.subject_id == subject.id

        pairs = {(inst.visit_instance_id, inst.form_definition_id) for inst in instances}
        expected_pairs = {
            (visit1.id, form_dm.id),
            (visit2.id, form_ae.id),
        }
        assert pairs == expected_pairs
        design_service.get_schedule_of_assessment.assert_awaited_once_with(
            mock_session, study_version_id
        )

    async def test_no_scheduled_forms_returns_empty_list(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        """An empty SoA creates no form instances."""
        subject = _make_subject(study_version_id)
        design_service.get_schedule_of_assessment.return_value = _schedule()

        with patch("app.services.edc.form_instance_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert instances == []
        mock_session.add.assert_not_called()
        mock_session.execute.assert_not_awaited()

    async def test_no_visit_instances_returns_empty_list(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        """No visit instances means no form instances are created."""
        subject = _make_subject(study_version_id)
        form_dm = _make_form_definition(study_version_id, "DM", 0)
        visit_definition_id = uuid.uuid4()
        design_service.get_schedule_of_assessment.return_value = _schedule(
            (visit_definition_id, form_dm.id)
        )

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=visit_result)

        with patch("app.services.edc.form_instance_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert instances == []

    async def test_writes_audit_events_for_each_instance(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        """An Audit_Event is recorded for each created FormInstance."""
        subject = _make_subject(study_version_id)
        visit = _make_visit_instance(subject.id, "Visit 1")
        form_dm = _make_form_definition(study_version_id, "DM", 0)
        design_service.get_schedule_of_assessment.return_value = _schedule(
            (visit.visit_definition_id, form_dm.id)
        )

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit]
        mock_session.execute = AsyncMock(return_value=visit_result)

        with patch("app.services.edc.form_instance_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.initialize_instances(mock_session, subject, actor_id)

            # One audit event per form instance
            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "form_instance"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["actor_id"] == actor_id
            assert call_kwargs["study_id"] == subject.study_id
            assert call_kwargs["site_id"] == subject.site_id
            assert call_kwargs["subject_id"] == subject.id

    async def test_repeating_form_creates_one_instance_per_visit(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        """Repeating forms get one empty FormInstance per visit (records added later)."""
        subject = _make_subject(study_version_id)
        visit = _make_visit_instance(subject.id, "Visit 1")
        form_ae = _make_form_definition(study_version_id, "AE", 0, is_repeating=True)
        design_service.get_schedule_of_assessment.return_value = _schedule(
            (visit.visit_definition_id, form_ae.id)
        )

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit]
        mock_session.execute = AsyncMock(return_value=visit_result)

        with patch("app.services.edc.form_instance_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert len(instances) == 1
        assert instances[0].form_definition_id == form_ae.id
        assert instances[0].visit_instance_id == visit.id
        assert instances[0].status == FormInstanceStatus.not_started

    async def test_procedure_only_entries_do_not_create_form_instances(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        subject = _make_subject(study_version_id)
        visit = _make_visit_instance(subject.id, "Visit 1")
        design_service.get_schedule_of_assessment.return_value = _schedule(
            (visit.visit_definition_id, None)
        )

        instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert instances == []
        mock_session.add.assert_not_called()
        mock_session.execute.assert_not_awaited()

    async def test_duplicate_schedule_entries_create_one_form_instance(
        self, service, design_service, mock_session, actor_id, study_version_id
    ):
        subject = _make_subject(study_version_id)
        visit = _make_visit_instance(subject.id, "Visit 1")
        form = _make_form_definition(study_version_id)
        pair = (visit.visit_definition_id, form.id)
        design_service.get_schedule_of_assessment.return_value = _schedule(pair, pair)
        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit]
        mock_session.execute = AsyncMock(return_value=visit_result)

        with patch("app.services.edc.form_instance_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(mock_session, subject, actor_id)

        assert len(instances) == 1
        mock_session.add.assert_called_once()


class TestFormInstanceServiceSingleton:
    def test_singleton_exists(self):
        assert form_instance_service is not None
        assert isinstance(form_instance_service, FormInstanceService)
