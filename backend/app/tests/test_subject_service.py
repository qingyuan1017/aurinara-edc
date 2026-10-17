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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.schemas.edc.subject import SubjectCreate
from app.services.edc.subject_service import SubjectService, subject_service


@pytest.fixture
def design_service():
    service = MagicMock()
    service.get_schedule_of_assessment = AsyncMock(return_value=SimpleNamespace(entries=()))
    service.list_subject_phase_definitions = AsyncMock(return_value=[])
    service.list_subject_phase_transitions = AsyncMock(return_value=[])
    service.list_arm_definitions = AsyncMock(return_value=[])
    return service


@pytest.fixture
def service(design_service):
    """Fresh SubjectService instance for each test."""
    return SubjectService(design_service=design_service)


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
        initial_visit_id = uuid.uuid4()
        service._design.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=uuid.uuid4(),
                phase_type="registered",
                visit_definition_ids=(initial_visit_id,),
            )
        ]

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
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.edc.visit_service.visit_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ) as mock_init,
            patch(
                "app.services.edc.form_instance_service.form_instance_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ) as mock_form_init,
        ):
            mock_audit.record = AsyncMock()
            subject = await service.create_subject(mock_session, study_id, data, actor_id)

        assert subject.study_id == study_id
        assert subject.site_id == site_id
        assert subject.study_version_id == version.id
        assert subject.status == SubjectStatus.screening
        assert subject.created_by == actor_id
        # Generated id follows {site_number}-{sequence}
        assert subject.subject_number == "101-0001"
        # Visit_Instances are initialized from the bound version (Req 7.4, 8.2)
        mock_init.assert_awaited_once_with(
            mock_session,
            subject,
            actor_id,
            definition_ids={initial_visit_id},
        )
        # Form_Instances are initialized from the bound version (Req 7.4)
        mock_form_init.assert_awaited_once_with(
            mock_session,
            subject,
            actor_id,
            definition_ids={initial_visit_id},
        )

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
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.edc.visit_service.visit_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.edc.form_instance_service.form_instance_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ),
        ):
            mock_audit.record = AsyncMock()
            subject = await service.create_subject(mock_session, study_id, data, actor_id)

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

    async def test_create_subject_rejects_inactive_site(
        self, service, mock_session, actor_id, study_id, site_id
    ):
        """Enrollment cannot create a subject at a deactivated site."""
        site = _make_site(site_id, study_id)
        site.status = SiteStatus.inactive
        mock_session.execute = AsyncMock(side_effect=_execute_side_effect(("first", site)))

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.create_subject(
                mock_session,
                study_id,
                SubjectCreate(site_id=site_id),
                actor_id,
            )

        assert "active site" in exc_info.value.message

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
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.edc.visit_service.visit_service.initialize_instances",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.edc.form_instance_service.form_instance_service.initialize_instances",
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


class TestSubjectPhaseState:
    """Operational phase selection, arm assignment, and visit visibility."""

    async def test_phase_state_offers_only_outgoing_flow_targets(
        self, service, design_service, mock_session
    ):
        current = SimpleNamespace(
            id=uuid.uuid4(),
            name="Registered",
            phase_type="registered",
            display_order=1,
            visit_definition_ids=(),
        )
        next_phase = SimpleNamespace(
            id=uuid.uuid4(),
            name="Treatment",
            phase_type="common",
            display_order=2,
            visit_definition_ids=(),
        )
        unreachable = SimpleNamespace(
            id=uuid.uuid4(),
            name="Complete",
            phase_type="complete",
            display_order=3,
            visit_definition_ids=(),
        )
        subject = _make_subject()
        subject.current_phase_definition_id = current.id
        design_service.list_subject_phase_definitions.return_value = [
            current,
            next_phase,
            unreachable,
        ]
        design_service.list_subject_phase_transitions.return_value = [
            SimpleNamespace(from_phase_id=current.id, to_phase_id=next_phase.id)
        ]

        state = await service.get_phase_state(mock_session, subject)

        assert [phase["id"] for phase in state["next_phases"]] == [next_phase.id]

    async def test_phase_update_rejects_jump_outside_configured_flow(
        self, service, design_service, mock_session, actor_id
    ):
        current_id = uuid.uuid4()
        allowed = SimpleNamespace(
            id=uuid.uuid4(),
            name="Treatment",
            phase_type="common",
            display_order=2,
            visit_definition_ids=(),
        )
        blocked = SimpleNamespace(
            id=uuid.uuid4(),
            name="Complete",
            phase_type="complete",
            display_order=3,
            visit_definition_ids=(),
        )
        subject = _make_subject()
        subject.current_phase_definition_id = current_id
        design_service.list_subject_phase_definitions.return_value = [allowed, blocked]
        design_service.list_subject_phase_transitions.return_value = [
            SimpleNamespace(from_phase_id=current_id, to_phase_id=allowed.id)
        ]

        with pytest.raises(ValidationError, match="not a valid next step"):
            await service.update_phase(
                mock_session,
                subject,
                phase_definition_id=blocked.id,
                arm_definition_id=None,
                actor_id=actor_id,
            )

        assert subject.current_phase_definition_id == current_id

    async def test_arm_phase_requires_and_persists_configured_arm(
        self, service, design_service, mock_session, actor_id
    ):
        subject = _make_subject()
        phase = SimpleNamespace(
            id=uuid.uuid4(),
            name="Randomization",
            phase_type="arm",
            display_order=1,
            visit_definition_ids=(),
        )
        arm = SimpleNamespace(
            id=uuid.uuid4(),
            name="Arm A",
            display_order=1,
            description=None,
        )
        design_service.list_subject_phase_definitions.return_value = [phase]
        design_service.list_arm_definitions.return_value = [arm]
        with pytest.raises(ValidationError, match="arm must be selected"):
            await service.update_phase(
                mock_session,
                subject,
                phase_definition_id=phase.id,
                arm_definition_id=None,
                actor_id=actor_id,
            )

        with (
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch("app.services.edc.form_instance_service.form_instance_service") as mock_forms,
            patch("app.services.edc.visit_service.visit_service") as mock_visits,
        ):
            mock_audit.record = AsyncMock()
            mock_forms.initialize_instances = AsyncMock(return_value=[])
            mock_visits.initialize_instances = AsyncMock(return_value=[])
            await service.update_phase(
                mock_session,
                subject,
                phase_definition_id=phase.id,
                arm_definition_id=arm.id,
                actor_id=actor_id,
            )

        assert subject.current_phase_definition_id == phase.id
        assert subject.arm_definition_id == arm.id
        mock_audit.record.assert_awaited_once()
        mock_visits.initialize_instances.assert_not_awaited()
        mock_forms.initialize_instances.assert_not_awaited()
        design_service.get_schedule_of_assessment.assert_not_awaited()

    async def test_complete_phase_marks_subject_completed_and_materializes_visits(
        self, service, design_service, mock_session, actor_id
    ):
        subject = _make_subject(status=SubjectStatus.on_treatment)
        visit_id = uuid.uuid4()
        phase = SimpleNamespace(
            id=uuid.uuid4(),
            name="Complete",
            phase_type="complete",
            display_order=9,
            visit_definition_ids=(visit_id,),
        )
        design_service.list_subject_phase_definitions.return_value = [phase]

        with (
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch("app.services.edc.form_instance_service.form_instance_service") as mock_forms,
            patch("app.services.edc.visit_service.visit_service") as mock_visits,
        ):
            mock_audit.record = AsyncMock()
            mock_forms.initialize_instances = AsyncMock(return_value=[])
            mock_visits.initialize_instances = AsyncMock(return_value=[])
            await service.update_phase(
                mock_session,
                subject,
                phase_definition_id=phase.id,
                arm_definition_id=None,
                actor_id=actor_id,
            )

        assert subject.status == SubjectStatus.completed
        mock_visits.initialize_instances.assert_awaited_once_with(
            mock_session,
            subject,
            actor_id,
            definition_ids={visit_id},
            skip_existing=True,
        )
        mock_forms.initialize_instances.assert_awaited_once_with(
            mock_session,
            subject,
            actor_id,
            skip_existing=True,
            arm_definition_id=None,
            definition_ids={visit_id},
        )

    async def test_common_phase_materializes_its_visits_and_forms(
        self, service, design_service, mock_session, actor_id
    ):
        subject = _make_subject()
        subject.arm_definition_id = uuid.uuid4()
        visit_id = uuid.uuid4()
        phase = SimpleNamespace(
            id=uuid.uuid4(),
            name="Follow-up",
            phase_type="common",
            display_order=2,
            visit_definition_ids=(visit_id,),
        )
        design_service.list_subject_phase_definitions.return_value = [phase]
        design_service.get_schedule_of_assessment.return_value = SimpleNamespace(
            entries=(SimpleNamespace(visit_definition_id=visit_id),)
        )

        with (
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch("app.services.edc.form_instance_service.form_instance_service") as mock_forms,
            patch("app.services.edc.visit_service.visit_service") as mock_visits,
        ):
            mock_audit.record = AsyncMock()
            mock_forms.initialize_instances = AsyncMock(return_value=[])
            mock_visits.initialize_instances = AsyncMock(return_value=[])
            await service.update_phase(
                mock_session,
                subject,
                phase_definition_id=phase.id,
                arm_definition_id=None,
                actor_id=actor_id,
            )

        mock_visits.initialize_instances.assert_awaited_once_with(
            mock_session,
            subject,
            actor_id,
            definition_ids={visit_id},
            skip_existing=True,
        )
        mock_forms.initialize_instances.assert_awaited_once_with(
            mock_session,
            subject,
            actor_id,
            skip_existing=True,
            arm_definition_id=subject.arm_definition_id,
            definition_ids={visit_id},
        )

    async def test_phase_path_shows_cumulative_visits_without_future_visits(
        self, service, design_service, mock_session
    ):
        prior_id = uuid.uuid4()
        current_id = uuid.uuid4()
        future_id = uuid.uuid4()
        subject = _make_subject()
        prior_phase_id = uuid.uuid4()
        subject.current_phase_definition_id = uuid.uuid4()
        design_service.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=prior_phase_id,
                name="Screening",
                phase_type="registered",
                display_order=1,
                visit_definition_ids=(prior_id,),
            ),
            SimpleNamespace(
                id=subject.current_phase_definition_id,
                name="Treatment",
                phase_type="common",
                display_order=2,
                visit_definition_ids=(current_id,),
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                name="Follow-up",
                phase_type="common",
                display_order=3,
                visit_definition_ids=(future_id,),
            ),
        ]
        visits = [
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=prior_id,
                design_version_id=subject.study_version_id,
                name="Prior",
                status=VisitInstanceStatus.scheduled,
            ),
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=current_id,
                design_version_id=subject.study_version_id,
                name="Current",
                status=VisitInstanceStatus.scheduled,
            ),
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=future_id,
                design_version_id=subject.study_version_id,
                name="Future",
                status=VisitInstanceStatus.scheduled,
            ),
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=None,
                design_version_id=subject.study_version_id,
                name="Unscheduled",
                status=VisitInstanceStatus.unscheduled,
            ),
        ]
        history_result = MagicMock()
        history_result.all.return_value = [
            (
                "phase_transition",
                str(prior_phase_id),
                str(subject.current_phase_definition_id),
            )
        ]
        visits_result = MagicMock()
        visits_result.scalars.return_value.all.return_value = visits
        mock_session.execute.side_effect = [history_result, visits_result]

        visible = await service.list_visible_visits(mock_session, subject)

        assert [visit.name for visit in visible] == ["Prior", "Current", "Unscheduled"]

    async def test_reversed_phase_visits_are_removed_from_visible_casebook_path(
        self, service, design_service, mock_session
    ):
        registered_phase_id = uuid.uuid4()
        treatment_phase_id = uuid.uuid4()
        follow_up_phase_id = uuid.uuid4()
        registered_visit_id = uuid.uuid4()
        treatment_visit_id = uuid.uuid4()
        follow_up_visit_id = uuid.uuid4()
        subject = _make_subject()
        subject.current_phase_definition_id = treatment_phase_id
        design_service.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=registered_phase_id,
                phase_type="registered",
                visit_definition_ids=(registered_visit_id,),
            ),
            SimpleNamespace(
                id=treatment_phase_id,
                phase_type="common",
                visit_definition_ids=(treatment_visit_id,),
            ),
            SimpleNamespace(
                id=follow_up_phase_id,
                phase_type="common",
                visit_definition_ids=(follow_up_visit_id,),
            ),
        ]
        history_result = MagicMock()
        history_result.all.return_value = [
            ("phase_transition", str(registered_phase_id), str(treatment_phase_id)),
            ("phase_transition", str(treatment_phase_id), str(follow_up_phase_id)),
            ("phase_reversal", str(follow_up_phase_id), str(treatment_phase_id)),
        ]
        visits_result = MagicMock()
        visits_result.scalars.return_value.all.return_value = [
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=registered_visit_id,
                design_version_id=subject.study_version_id,
                name="Registered",
                status=VisitInstanceStatus.scheduled,
            ),
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=treatment_visit_id,
                design_version_id=subject.study_version_id,
                name="Treatment",
                status=VisitInstanceStatus.scheduled,
            ),
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=subject.id,
                visit_definition_id=follow_up_visit_id,
                design_version_id=subject.study_version_id,
                name="Follow-up",
                status=VisitInstanceStatus.scheduled,
            ),
        ]
        mock_session.execute.side_effect = [history_result, visits_result]

        visible = await service.list_visible_visits(mock_session, subject)

        assert [visit.name for visit in visible] == ["Registered", "Treatment"]

    async def test_phase_path_can_branch_after_reversal(
        self, service, design_service, mock_session
    ):
        registered_phase_id = uuid.uuid4()
        treatment_phase_id = uuid.uuid4()
        first_follow_up_phase_id = uuid.uuid4()
        alternate_follow_up_phase_id = uuid.uuid4()
        visit_ids = [uuid.uuid4() for _ in range(4)]
        subject = _make_subject()
        subject.current_phase_definition_id = alternate_follow_up_phase_id
        design_service.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=phase_id,
                phase_type="registered" if index == 0 else "common",
                visit_definition_ids=(visit_ids[index],),
            )
            for index, phase_id in enumerate(
                (
                    registered_phase_id,
                    treatment_phase_id,
                    first_follow_up_phase_id,
                    alternate_follow_up_phase_id,
                )
            )
        ]
        history_result = MagicMock()
        history_result.all.return_value = [
            ("phase_transition", str(registered_phase_id), str(treatment_phase_id)),
            ("phase_transition", str(treatment_phase_id), str(first_follow_up_phase_id)),
            ("phase_reversal", str(first_follow_up_phase_id), str(treatment_phase_id)),
            (
                "phase_transition",
                str(treatment_phase_id),
                str(alternate_follow_up_phase_id),
            ),
        ]
        mock_session.execute.return_value = history_result

        allowed = await service.visible_visit_definition_ids(mock_session, subject)

        assert allowed == {visit_ids[0], visit_ids[1], visit_ids[3]}

    async def test_no_phase_configuration_exposes_all_visit_definitions(
        self, service, design_service, mock_session
    ):
        subject = _make_subject()
        design_service.list_subject_phase_definitions.return_value = []

        allowed = await service.visible_visit_definition_ids(mock_session, subject)

        assert allowed is None

    async def test_configured_phases_without_current_phase_expose_no_visits(
        self, service, design_service, mock_session
    ):
        subject = _make_subject()
        design_service.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=uuid.uuid4(),
                name="Registered",
                phase_type="registered",
                display_order=1,
                visit_definition_ids=(uuid.uuid4(),),
            )
        ]
        history_result = MagicMock()
        history_result.all.return_value = []
        mock_session.execute.return_value = history_result

        allowed = await service.visible_visit_definition_ids(mock_session, subject)

        assert allowed == set()

    async def test_current_arm_phase_adds_no_visits(self, service, design_service, mock_session):
        subject = _make_subject()
        subject.current_phase_definition_id = uuid.uuid4()
        subject.arm_definition_id = uuid.uuid4()
        allowed_id = uuid.uuid4()
        design_service.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=subject.current_phase_definition_id,
                name="Treatment",
                phase_type="arm",
                display_order=2,
                visit_definition_ids=(),
            )
        ]
        design_service.get_schedule_of_assessment.return_value = SimpleNamespace(
            entries=(SimpleNamespace(visit_definition_id=allowed_id),)
        )
        history_result = MagicMock()
        history_result.all.return_value = []
        mock_session.execute.return_value = history_result

        allowed = await service.visible_visit_definition_ids(mock_session, subject)

        assert allowed == set()
        design_service.get_schedule_of_assessment.assert_awaited_once_with(
            mock_session,
            subject.study_version_id,
            subject.arm_definition_id,
        )

    async def test_phase_after_arm_adds_only_phase_visits_in_selected_arm_soa(
        self, service, design_service, mock_session
    ):
        subject = _make_subject()
        registered_phase_id = uuid.uuid4()
        arm_phase_id = uuid.uuid4()
        current_phase_id = uuid.uuid4()
        subject.current_phase_definition_id = current_phase_id
        subject.arm_definition_id = uuid.uuid4()
        prior_visit_id = uuid.uuid4()
        allowed_visit_id = uuid.uuid4()
        phase_only_visit_id = uuid.uuid4()
        arm_only_visit_id = uuid.uuid4()
        design_service.list_subject_phase_definitions.return_value = [
            SimpleNamespace(
                id=registered_phase_id,
                phase_type="registered",
                visit_definition_ids=(prior_visit_id,),
            ),
            SimpleNamespace(
                id=arm_phase_id,
                phase_type="arm",
                visit_definition_ids=(),
            ),
            SimpleNamespace(
                id=current_phase_id,
                phase_type="common",
                visit_definition_ids=(allowed_visit_id, phase_only_visit_id),
            ),
        ]
        design_service.get_schedule_of_assessment.return_value = SimpleNamespace(
            entries=(
                SimpleNamespace(visit_definition_id=allowed_visit_id),
                SimpleNamespace(visit_definition_id=arm_only_visit_id),
            )
        )
        history_result = MagicMock()
        history_result.all.return_value = [
            ("phase_transition", str(registered_phase_id), str(arm_phase_id)),
            ("phase_transition", str(arm_phase_id), str(current_phase_id)),
        ]
        mock_session.execute.return_value = history_result

        allowed = await service.visible_visit_definition_ids(mock_session, subject)

        assert allowed == {prior_visit_id, allowed_visit_id}

    async def test_reverse_phase_restores_previous_phase_without_deleting_data(
        self, service, design_service, mock_session, actor_id
    ):
        previous_phase = SimpleNamespace(
            id=uuid.uuid4(),
            name="Treatment",
            phase_type="common",
            display_order=2,
            visit_definition_ids=(),
        )
        current_phase = SimpleNamespace(
            id=uuid.uuid4(),
            name="Complete",
            phase_type="complete",
            display_order=3,
            visit_definition_ids=(),
        )
        subject = _make_subject(status=SubjectStatus.completed)
        subject.current_phase_definition_id = current_phase.id
        design_service.list_subject_phase_definitions.return_value = [
            previous_phase,
            current_phase,
        ]

        with (
            patch.object(
                service,
                "_previous_phase_id",
                AsyncMock(return_value=previous_phase.id),
            ),
            patch.object(
                service,
                "_entered_phase_path",
                AsyncMock(return_value=[previous_phase.id, current_phase.id]),
            ),
            patch(
                "app.services.edc.subject_service.lock_service.is_modification_blocked",
                AsyncMock(return_value=False),
            ),
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
        ):
            mock_audit.record = AsyncMock()
            reversed_subject = await service.reverse_phase(
                mock_session,
                subject,
                reason="Complete phase selected in error",
                actor_id=actor_id,
            )

        assert reversed_subject.current_phase_definition_id == previous_phase.id
        assert reversed_subject.status == SubjectStatus.on_treatment
        mock_session.flush.assert_awaited_once()
        mock_session.delete.assert_not_awaited()
        assert mock_audit.record.await_args.kwargs["action"] == "phase_reversal"
        assert mock_audit.record.await_args.kwargs["reason"] == ("Complete phase selected in error")


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
            (SubjectStatus.screening, SubjectStatus.inactive),
            (SubjectStatus.enrolled, SubjectStatus.discontinued),
            (SubjectStatus.inactive, SubjectStatus.discontinued),
        ],
    )
    async def test_legal_transitions_succeed(
        self, service, mock_session, actor_id, current, target
    ):
        """All legal subject transitions succeed (Req 7.3)."""
        subject = _make_subject(status=current)

        with (
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
            patch(
                "app.services.edc.subject_service.lock_service.is_modification_blocked",
                AsyncMock(return_value=False),
            ),
        ):
            mock_audit.record = AsyncMock()
            result = await service.transition_status(
                mock_session, subject, target, actor_id, reason="Lifecycle correction"
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

    async def test_transition_writes_audit_event(self, service, mock_session, actor_id):
        """transition_status writes an Audit_Event with old/new status (Req 7.6)."""
        subject = _make_subject(status=SubjectStatus.screening)

        with patch("app.services.edc.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.transition_status(mock_session, subject, SubjectStatus.enrolled, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "subject"
            assert call_kwargs["action"] == "status_transition"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == "Screening"
            assert call_kwargs["new_value"] == "Enrolled"
            assert call_kwargs["actor_id"] == actor_id

    async def test_transition_to_same_status_raises_error(self, service, mock_session, actor_id):
        """Transitioning to the same status is not allowed."""
        subject = _make_subject(status=SubjectStatus.enrolled)

        with pytest.raises(BusinessRuleError):
            await service.transition_status(mock_session, subject, SubjectStatus.enrolled, actor_id)

    async def test_inactive_requires_reason(self, service, mock_session, actor_id):
        subject = _make_subject(status=SubjectStatus.screening)

        with pytest.raises(ValidationError):
            await service.transition_status(
                mock_session,
                subject,
                SubjectStatus.inactive,
                actor_id,
                reason="  ",
            )

    async def test_discontinue_rejects_locked_subject(self, service, mock_session, actor_id):
        subject = _make_subject(status=SubjectStatus.on_treatment)

        with (
            patch(
                "app.services.edc.subject_service.lock_service.is_modification_blocked",
                AsyncMock(return_value=True),
            ),
            pytest.raises(BusinessRuleError) as exc_info,
        ):
            await service.transition_status(
                mock_session,
                subject,
                SubjectStatus.discontinued,
                actor_id,
                reason="Participation ended",
            )

        assert exc_info.value.details["reason"] == "SUBJECT_LIFECYCLE_CHANGE_LOCKED"


class TestGetCasebook:
    """Tests for SubjectService.get_casebook()."""

    async def test_get_casebook_returns_structure(self, service, mock_session):
        """get_casebook returns the subject envelope with clinical status (Req 7.5).

        With no visit or form instances the visit list is empty; the subject
        lookup resolves via ``.scalars().first()`` while the visit/form queries
        resolve via ``.scalars().all()``.
        """
        subject = _make_subject(status=SubjectStatus.enrolled)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = subject
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        casebook = await service.get_casebook(mock_session, subject.id)

        assert casebook["subject_id"] == subject.id
        assert casebook["subject_number"] == subject.subject_number
        assert casebook["status"] == SubjectStatus.enrolled
        assert casebook["study_version_id"] == subject.study_version_id
        assert casebook["visits"] == []

    async def test_get_casebook_includes_visit_instances_and_their_forms(
        self, service, design_service, mock_session
    ):
        """Casebook surfaces the subject's visit instances with their forms (Req 7.5).

        Regression: get_casebook previously returned an empty visit list even
        when visit instances existed, so the subject casebook showed "no visits
        scheduled" while Manage Visits listed them.
        """
        subject = _make_subject(status=SubjectStatus.enrolled)

        visit = SimpleNamespace(
            id=uuid.uuid4(),
            visit_definition_id=uuid.uuid4(),
            name="Baseline",
            status="scheduled",
            visit_date=None,
            created_at=datetime.now(UTC),
        )
        form = SimpleNamespace(
            id=uuid.uuid4(),
            visit_instance_id=visit.id,
            form_definition_id=uuid.uuid4(),
            form_definition=SimpleNamespace(name="Vitals"),
            status="Not Started",
            created_at=datetime.now(UTC),
        )
        design_service.get_schedule_of_assessment.return_value = SimpleNamespace(
            entries=(
                SimpleNamespace(
                    visit_definition_id=visit.visit_definition_id,
                    form_definition_id=form.form_definition_id,
                ),
            )
        )

        subject_result = MagicMock()
        subject_result.scalars.return_value.first.return_value = subject
        visits_result = MagicMock()
        visits_result.scalars.return_value.all.return_value = [visit]
        forms_result = MagicMock()
        forms_result.scalars.return_value.all.return_value = [form]
        mock_session.execute = AsyncMock(side_effect=[subject_result, visits_result, forms_result])

        casebook = await service.get_casebook(mock_session, subject.id)

        assert len(casebook["visits"]) == 1
        entry = casebook["visits"][0]
        assert entry["visit_instance_id"] == visit.id
        assert entry["name"] == "Baseline"
        assert len(entry["forms"]) == 1
        assert entry["forms"][0]["form_instance_id"] == form.id
        assert entry["forms"][0]["name"] == "Vitals"

    async def test_get_casebook_hides_forms_not_in_schedule(
        self, service, design_service, mock_session
    ):
        """Unchecked SoA cells are excluded from the casebook."""
        subject = _make_subject(status=SubjectStatus.enrolled)
        visit = SimpleNamespace(
            id=uuid.uuid4(),
            visit_definition_id=uuid.uuid4(),
            name="Screening",
            status="scheduled",
            visit_date=None,
            created_at=datetime.now(UTC),
        )
        scheduled_form_id = uuid.uuid4()
        unscheduled_form_id = uuid.uuid4()
        scheduled = SimpleNamespace(
            id=uuid.uuid4(),
            visit_instance_id=visit.id,
            form_definition_id=scheduled_form_id,
            form_definition=SimpleNamespace(name="Vitals"),
            status="Not Started",
            created_at=datetime.now(UTC),
        )
        legacy_extra = SimpleNamespace(
            id=uuid.uuid4(),
            visit_instance_id=visit.id,
            form_definition_id=unscheduled_form_id,
            form_definition=SimpleNamespace(name="Physical Examination"),
            status="Not Started",
            created_at=datetime.now(UTC),
        )
        design_service.get_schedule_of_assessment.return_value = SimpleNamespace(
            entries=(
                SimpleNamespace(
                    visit_definition_id=visit.visit_definition_id,
                    form_definition_id=scheduled_form_id,
                ),
            )
        )

        subject_result = MagicMock()
        subject_result.scalars.return_value.first.return_value = subject
        visits_result = MagicMock()
        visits_result.scalars.return_value.all.return_value = [visit]
        forms_result = MagicMock()
        forms_result.scalars.return_value.all.return_value = [scheduled, legacy_extra]
        mock_session.execute = AsyncMock(side_effect=[subject_result, visits_result, forms_result])

        casebook = await service.get_casebook(mock_session, subject.id)

        assert [form["name"] for form in casebook["visits"][0]["forms"]] == ["Vitals"]

    async def test_get_casebook_missing_subject_raises_not_found(self, service, mock_session):
        """get_casebook raises NotFoundError for a missing subject."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_casebook(mock_session, uuid.uuid4())


class TestSoftDelete:
    """Tests for SubjectService.soft_delete()."""

    async def test_soft_delete_sets_deletion_fields(self, service, mock_session, actor_id):
        """soft_delete sets deleted_at/by/reason and retains the record (Req 22.2)."""
        subject = _make_subject()

        with patch("app.services.edc.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.soft_delete(
                mock_session,
                subject,
                "entered in error",
                actor_id,
                subject_number_confirmation=subject.subject_number,
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
            await service.soft_delete(
                mock_session,
                subject,
                "reason",
                actor_id,
                subject_number_confirmation=subject.subject_number,
            )

    async def test_soft_delete_writes_audit_event(self, service, mock_session, actor_id):
        """soft_delete writes an Audit_Event with the reason."""
        subject = _make_subject()

        with patch("app.services.edc.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.soft_delete(
                mock_session,
                subject,
                "duplicate",
                actor_id,
                subject_number_confirmation=subject.subject_number,
            )

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "subject"
            assert call_kwargs["action"] == "delete"
            assert call_kwargs["reason"] == "duplicate"
            assert call_kwargs["actor_id"] == actor_id

    async def test_soft_delete_rejects_non_screening_subject(self, service, mock_session, actor_id):
        subject = _make_subject(status=SubjectStatus.enrolled)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.soft_delete(
                mock_session,
                subject,
                "entered in error",
                actor_id,
                subject_number_confirmation=subject.subject_number,
            )

        assert exc_info.value.details["reason"] == "SUBJECT_REMOVAL_STATUS_NOT_ELIGIBLE"

    async def test_soft_delete_requires_exact_subject_number_confirmation(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()

        with pytest.raises(ValidationError) as exc_info:
            await service.soft_delete(
                mock_session,
                subject,
                "entered in error",
                actor_id,
                subject_number_confirmation="wrong",
            )

        assert exc_info.value.details["reason"] == "SUBJECT_NUMBER_CONFIRMATION_MISMATCH"

    async def test_soft_delete_rejects_subject_with_clinical_revision(
        self, service, mock_session, actor_id
    ):
        subject = _make_subject()
        subject.data_revision = 1

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.soft_delete(
                mock_session,
                subject,
                "entered in error",
                actor_id,
                subject_number_confirmation=subject.subject_number,
            )

        assert "CLINICAL_DATA" in exc_info.value.details["blockers"]


class TestRestoreSubject:
    async def test_restore_clears_deletion_state_and_audits(self, service, mock_session, actor_id):
        subject = _make_subject()
        subject.deleted_at = datetime.now(UTC)
        subject.deleted_by = uuid.uuid4()
        subject.deletion_reason = "duplicate"

        with patch("app.services.edc.subject_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            restored = await service.restore(
                mock_session,
                subject,
                "Deletion was applied to the wrong subject",
                actor_id,
            )

        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.deletion_reason is None
        assert mock_audit.record.await_args.kwargs["action"] == "restore"
        assert mock_audit.record.await_args.kwargs["reason"] == (
            "Deletion was applied to the wrong subject"
        )


class TestSwitchSubjectSite:
    async def test_switch_site_updates_only_site_and_audits(self, service, mock_session, actor_id):
        subject = _make_subject()
        old_site_id = subject.site_id
        new_site_id = uuid.uuid4()
        target_site = _make_site(new_site_id, subject.study_id)
        locked_result = MagicMock()
        locked_result.scalars.return_value.first.return_value = subject
        target_result = MagicMock()
        target_result.scalars.return_value.first.return_value = target_site
        mock_session.execute.side_effect = [locked_result, target_result]

        with (
            patch.object(
                service,
                "_subject_removal_blockers",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.edc.subject_service.lock_service.is_modification_blocked",
                AsyncMock(return_value=False),
            ),
            patch("app.services.edc.subject_service.audit_service") as mock_audit,
        ):
            mock_audit.record = AsyncMock()
            transferred = await service.switch_site(
                mock_session,
                subject,
                site_id=new_site_id,
                reason="Initially assigned to the wrong site",
                actor_id=actor_id,
            )

        assert transferred.site_id == new_site_id
        assert transferred.subject_number == "101-0001"
        audit = mock_audit.record.await_args.kwargs
        assert audit["action"] == "site_transfer"
        assert audit["old_value"] == str(old_site_id)
        assert audit["new_value"] == str(new_site_id)

    async def test_switch_site_rejects_downstream_records(self, service, mock_session, actor_id):
        subject = _make_subject()
        new_site_id = uuid.uuid4()
        target_site = _make_site(new_site_id, subject.study_id)
        locked_result = MagicMock()
        locked_result.scalars.return_value.first.return_value = subject
        target_result = MagicMock()
        target_result.scalars.return_value.first.return_value = target_site
        mock_session.execute.side_effect = [locked_result, target_result]

        with (
            patch.object(
                service,
                "_subject_removal_blockers",
                AsyncMock(return_value=["SAFETY_CASES"]),
            ),
            patch(
                "app.services.edc.subject_service.lock_service.is_modification_blocked",
                AsyncMock(return_value=False),
            ),
            pytest.raises(BusinessRuleError) as exc_info,
        ):
            await service.switch_site(
                mock_session,
                subject,
                site_id=new_site_id,
                reason="Initially assigned to the wrong site",
                actor_id=actor_id,
            )

        assert exc_info.value.details["reason"] == "SUBJECT_SITE_TRANSFER_HAS_RECORDS"
        assert exc_info.value.details["blockers"] == ["SAFETY_CASES"]


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
