"""Unit tests for the FormInstanceService.

Validates Requirements:
  - 7.4: When a Subject is created, Form_Instances are initialized for each
          form definition in the bound Study_Version, linked to visit instances.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.form_data import FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitInstance, VisitInstanceStatus
from app.services.form_instance_service import FormInstanceService, form_instance_service


@pytest.fixture
def service():
    """Fresh FormInstanceService instance for each test."""
    return FormInstanceService()


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


class TestInitializeInstances:
    """Tests for FormInstanceService.initialize_instances()."""

    async def test_creates_form_instance_per_visit_and_definition(
        self, service, mock_session, actor_id, study_version_id
    ):
        """Each (visit_instance, form_definition) pair gets one FormInstance (Req 7.4)."""
        subject = _make_subject(study_version_id)
        visit1 = _make_visit_instance(subject.id, "Screening")
        visit2 = _make_visit_instance(subject.id, "Baseline")
        form_dm = _make_form_definition(study_version_id, "DM", 0)
        form_ae = _make_form_definition(study_version_id, "AE", 1, is_repeating=True)

        # First execute: form definitions; Second execute: visit instances
        form_defs_result = MagicMock()
        form_defs_result.scalars.return_value.all.return_value = [form_dm, form_ae]

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit1, visit2]

        mock_session.execute = AsyncMock(
            side_effect=[form_defs_result, visit_result]
        )

        with patch(
            "app.services.form_instance_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(
                mock_session, subject, actor_id
            )

        # 2 visits x 2 form definitions = 4 form instances
        assert len(instances) == 4
        assert mock_session.add.call_count == 4

        # All have status "Not Started"
        for inst in instances:
            assert inst.status == FormInstanceStatus.not_started
            assert inst.subject_id == subject.id

        # Check we have every combination
        pairs = {(inst.visit_instance_id, inst.form_definition_id) for inst in instances}
        expected_pairs = {
            (visit1.id, form_dm.id),
            (visit1.id, form_ae.id),
            (visit2.id, form_dm.id),
            (visit2.id, form_ae.id),
        }
        assert pairs == expected_pairs

    async def test_no_form_definitions_returns_empty_list(
        self, service, mock_session, actor_id, study_version_id
    ):
        """No form definitions means no form instances are created."""
        subject = _make_subject(study_version_id)

        form_defs_result = MagicMock()
        form_defs_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(return_value=form_defs_result)

        with patch(
            "app.services.form_instance_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(
                mock_session, subject, actor_id
            )

        assert instances == []
        mock_session.add.assert_not_called()

    async def test_no_visit_instances_returns_empty_list(
        self, service, mock_session, actor_id, study_version_id
    ):
        """No visit instances means no form instances are created."""
        subject = _make_subject(study_version_id)
        form_dm = _make_form_definition(study_version_id, "DM", 0)

        form_defs_result = MagicMock()
        form_defs_result.scalars.return_value.all.return_value = [form_dm]

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[form_defs_result, visit_result]
        )

        with patch(
            "app.services.form_instance_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(
                mock_session, subject, actor_id
            )

        assert instances == []

    async def test_writes_audit_events_for_each_instance(
        self, service, mock_session, actor_id, study_version_id
    ):
        """An Audit_Event is recorded for each created FormInstance."""
        subject = _make_subject(study_version_id)
        visit = _make_visit_instance(subject.id, "Visit 1")
        form_dm = _make_form_definition(study_version_id, "DM", 0)

        form_defs_result = MagicMock()
        form_defs_result.scalars.return_value.all.return_value = [form_dm]

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit]

        mock_session.execute = AsyncMock(
            side_effect=[form_defs_result, visit_result]
        )

        with patch(
            "app.services.form_instance_service.audit_service"
        ) as mock_audit:
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
        self, service, mock_session, actor_id, study_version_id
    ):
        """Repeating forms get one empty FormInstance per visit (records added later)."""
        subject = _make_subject(study_version_id)
        visit = _make_visit_instance(subject.id, "Visit 1")
        form_ae = _make_form_definition(study_version_id, "AE", 0, is_repeating=True)

        form_defs_result = MagicMock()
        form_defs_result.scalars.return_value.all.return_value = [form_ae]

        visit_result = MagicMock()
        visit_result.scalars.return_value.all.return_value = [visit]

        mock_session.execute = AsyncMock(
            side_effect=[form_defs_result, visit_result]
        )

        with patch(
            "app.services.form_instance_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            instances = await service.initialize_instances(
                mock_session, subject, actor_id
            )

        assert len(instances) == 1
        assert instances[0].form_definition_id == form_ae.id
        assert instances[0].visit_instance_id == visit.id
        assert instances[0].status == FormInstanceStatus.not_started


class TestFormInstanceServiceSingleton:
    def test_singleton_exists(self):
        assert form_instance_service is not None
        assert isinstance(form_instance_service, FormInstanceService)
