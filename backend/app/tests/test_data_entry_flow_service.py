"""Unit tests for the DataEntryFlowService state machine.

Validates Requirements:
  - 7.1 / 7.10: Scope-gated site selection; out-of-scope site rejected.
  - 7.2:  Step ordering requires site -> subject -> visit -> form -> data.
  - 7.3 / 2.7: Adding a subject binds it to exactly one Published_Design.
  - 7.4:  A visit must be selected before form selection.
  - 7.5:  Unscheduled visits allowed only where the design permits them.
  - 7.6 / 7.7: Form fields come from the bound design; values persist as records.
  - 7.8:  Out-of-order advances are rejected; current step retained; error names
          the incomplete prior step.
  - 7.9 / 2.8: Subject creation with no Published_Design is rejected, data
          unchanged (delegated to subject_service which raises before any write).
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    AuthorizationError,
    BusinessRuleError,
    NotFoundError,
)
from app.models.edc.site import Site, SiteStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.schemas.edc.subject import SubjectCreate
from app.schemas.edc.visit import UnscheduledVisitCreate
from app.services.edc.data_entry_flow_service import (
    DataEntryFlowService,
    DataEntryFlowState,
    FlowStep,
    data_entry_flow_service,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def study_id():
    return uuid.uuid4()


@pytest.fixture
def site_id():
    return uuid.uuid4()


@pytest.fixture
def actor_id():
    return uuid.uuid4()


@pytest.fixture
def user():
    """A minimal user stand-in; the permission fake decides authorization."""
    return SimpleNamespace(id=uuid.uuid4())


def _make_site(site_id: uuid.UUID, study_id: uuid.UUID) -> Site:
    return Site(
        id=site_id,
        study_id=study_id,
        site_number="101",
        name="Test Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )


def _make_subject(
    study_id: uuid.UUID,
    site_id: uuid.UUID,
    design_version_id: uuid.UUID | None = None,
) -> Subject:
    return Subject(
        id=uuid.uuid4(),
        study_id=study_id,
        site_id=site_id,
        study_version_id=design_version_id or uuid.uuid4(),
        subject_number="101-0001",
        status=SubjectStatus.screening,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


def _site_session(site: Site | None):
    """AsyncSession mock whose single execute() returns the given site."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = site
    session.execute = AsyncMock(return_value=result)
    return session


def _allow_permissions():
    """Permission fake that passes every candidate site through (in scope)."""
    perms = MagicMock()
    perms.filter_sites = MagicMock(side_effect=lambda u, ids, mapping=None: list(ids))
    return perms


def _deny_permissions():
    """Permission fake that returns no sites (out of scope)."""
    perms = MagicMock()
    perms.filter_sites = MagicMock(return_value=[])
    return perms


def _make_service(**overrides) -> DataEntryFlowService:
    """Build a service with fakes; overrides replace specific collaborators."""
    defaults = {
        "permission_service": _allow_permissions(),
        "design_service": AsyncMock(),
        "subjects": AsyncMock(),
        "visits": AsyncMock(),
        "data_capture": AsyncMock(),
    }
    defaults.update(overrides)
    return DataEntryFlowService(**defaults)


# ---------------------------------------------------------------------------
# Step 1 — Site selection (R7.1, R7.10)
# ---------------------------------------------------------------------------


class TestSelectSite:
    async def test_in_scope_site_is_selected(self, study_id, site_id, user):
        site = _make_site(site_id, study_id)
        service = _make_service(permission_service=_allow_permissions())
        state = service.start(study_id)

        result = await service.select_site(
            _site_session(site), state, user, site_id
        )

        assert result.site_id == site_id
        assert result.current_step == FlowStep.SITE

    async def test_out_of_scope_site_is_rejected(self, study_id, site_id, user):
        """R7.10: an out-of-scope site is rejected with a not-authorized error."""
        site = _make_site(site_id, study_id)
        service = _make_service(permission_service=_deny_permissions())
        state = service.start(study_id)

        with pytest.raises(AuthorizationError) as exc_info:
            await service.select_site(_site_session(site), state, user, site_id)

        assert "scope" in exc_info.value.message.lower()
        # Current step retained — the flow did not advance.
        assert state.current_step == FlowStep.START
        assert state.site_id is None

    async def test_missing_site_raises_not_found(self, study_id, site_id, user):
        service = _make_service()
        state = service.start(study_id)

        with pytest.raises(NotFoundError):
            await service.select_site(_site_session(None), state, user, site_id)


# ---------------------------------------------------------------------------
# Step 2 — Subject selection / creation (R7.2, R7.3, R7.9, R2.7, R2.8)
# ---------------------------------------------------------------------------


class TestSubjectStep:
    async def test_add_subject_binds_published_design(
        self, study_id, site_id, actor_id
    ):
        """R7.3/R2.7: a new subject binds to exactly one Published_Design."""
        design_version_id = uuid.uuid4()
        subject = _make_subject(study_id, site_id, design_version_id)
        subjects = AsyncMock()
        subjects.create_subject = AsyncMock(return_value=subject)
        service = _make_service(subjects=subjects)

        state = DataEntryFlowState(
            study_id=study_id, site_id=site_id, current_step=FlowStep.SITE
        )
        data = SubjectCreate(site_id=site_id)

        result = await service.add_subject(AsyncMock(), state, data, actor_id)

        assert result.subject_id == subject.id
        assert result.design_version_id == design_version_id
        assert result.current_step == FlowStep.SUBJECT

    async def test_add_subject_forces_selected_site(
        self, study_id, site_id, actor_id
    ):
        """A new subject is bound to the already-selected site, not another one."""
        subject = _make_subject(study_id, site_id)
        subjects = AsyncMock()
        subjects.create_subject = AsyncMock(return_value=subject)
        service = _make_service(subjects=subjects)

        state = DataEntryFlowState(
            study_id=study_id, site_id=site_id, current_step=FlowStep.SITE
        )
        # Caller passes a *different* site_id; the flow must override it.
        data = SubjectCreate(site_id=uuid.uuid4())

        await service.add_subject(AsyncMock(), state, data, actor_id)

        passed_data = subjects.create_subject.call_args.args[2]
        assert passed_data.site_id == site_id

    async def test_add_subject_without_site_rejected(self, study_id, actor_id):
        """R7.8: cannot add a subject before completing site selection."""
        service = _make_service()
        state = service.start(study_id)
        data = SubjectCreate(site_id=uuid.uuid4())

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.add_subject(AsyncMock(), state, data, actor_id)

        assert exc_info.value.details["incomplete_prior_step"] == "site selection"
        assert state.current_step == FlowStep.START
        assert state.subject_id is None

    async def test_add_subject_no_published_design_propagates(
        self, study_id, site_id, actor_id
    ):
        """R7.9/R2.8: when no Published_Design exists, creation is rejected.

        subject_service raises before any write, so study data is unchanged and
        the flow does not advance.
        """
        subjects = AsyncMock()
        subjects.create_subject = AsyncMock(
            side_effect=BusinessRuleError(
                message="Study has no published version; cannot enroll subjects"
            )
        )
        service = _make_service(subjects=subjects)
        state = DataEntryFlowState(
            study_id=study_id, site_id=site_id, current_step=FlowStep.SITE
        )
        data = SubjectCreate(site_id=site_id)

        with pytest.raises(BusinessRuleError):
            await service.add_subject(AsyncMock(), state, data, actor_id)

        # Flow retained at the site step; no subject bound.
        assert state.current_step == FlowStep.SITE
        assert state.subject_id is None
        assert state.design_version_id is None

    async def test_select_existing_subject_captures_binding(
        self, study_id, site_id
    ):
        design_version_id = uuid.uuid4()
        subject = _make_subject(study_id, site_id, design_version_id)
        subjects = AsyncMock()
        subjects.get_subject = AsyncMock(return_value=subject)
        service = _make_service(subjects=subjects)

        state = DataEntryFlowState(
            study_id=study_id, site_id=site_id, current_step=FlowStep.SITE
        )

        result = await service.select_subject(AsyncMock(), state, subject.id)

        assert result.subject_id == subject.id
        assert result.design_version_id == design_version_id
        assert result.current_step == FlowStep.SUBJECT

    async def test_select_subject_wrong_site_rejected(self, study_id, site_id):
        other_site = uuid.uuid4()
        subject = _make_subject(study_id, other_site)
        subjects = AsyncMock()
        subjects.get_subject = AsyncMock(return_value=subject)
        service = _make_service(subjects=subjects)

        state = DataEntryFlowState(
            study_id=study_id, site_id=site_id, current_step=FlowStep.SITE
        )

        with pytest.raises(BusinessRuleError):
            await service.select_subject(AsyncMock(), state, subject.id)


# ---------------------------------------------------------------------------
# Step 3 — Visit selection / unscheduled creation (R7.4, R7.5)
# ---------------------------------------------------------------------------


class TestVisitStep:
    async def test_select_visit_requires_subject(self, study_id, site_id):
        """R7.8: cannot select a visit before completing subject selection."""
        service = _make_service()
        state = DataEntryFlowState(
            study_id=study_id, site_id=site_id, current_step=FlowStep.SITE
        )

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.select_visit(AsyncMock(), state, uuid.uuid4())

        assert (
            exc_info.value.details["incomplete_prior_step"] == "subject selection"
        )
        assert state.current_step == FlowStep.SITE

    async def test_select_scheduled_visit(self, study_id, site_id):
        subject_id = uuid.uuid4()
        instance = SimpleNamespace(id=uuid.uuid4(), subject_id=subject_id)
        visits = AsyncMock()
        visits.get_instance = AsyncMock(return_value=instance)
        service = _make_service(visits=visits)

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            design_version_id=uuid.uuid4(),
            current_step=FlowStep.SUBJECT,
        )

        result = await service.select_visit(AsyncMock(), state, instance.id)

        assert result.visit_instance_id == instance.id
        assert result.current_step == FlowStep.VISIT

    async def test_unscheduled_visit_allowed_when_design_permits(
        self, study_id, site_id, actor_id
    ):
        """R7.5: unscheduled visit allowed where the bound design permits it."""
        subject_id = uuid.uuid4()
        design_version_id = uuid.uuid4()
        instance = SimpleNamespace(id=uuid.uuid4(), subject_id=subject_id)

        design = AsyncMock()
        design.permits_unscheduled_visits = AsyncMock(return_value=True)
        subjects = AsyncMock()
        subjects.get_subject = AsyncMock(
            return_value=_make_subject(study_id, site_id, design_version_id)
        )
        visits = AsyncMock()
        visits.create_unscheduled = AsyncMock(return_value=instance)
        service = _make_service(
            design_service=design, subjects=subjects, visits=visits
        )

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            design_version_id=design_version_id,
            current_step=FlowStep.SUBJECT,
        )
        data = UnscheduledVisitCreate(name="Unscheduled follow-up")

        result = await service.create_unscheduled_visit(
            AsyncMock(), state, data, actor_id
        )

        assert result.visit_instance_id == instance.id
        assert result.current_step == FlowStep.VISIT

    async def test_unscheduled_visit_rejected_when_design_forbids(
        self, study_id, site_id, actor_id
    ):
        """R7.5: unscheduled visit rejected where the design does not permit it."""
        design_version_id = uuid.uuid4()
        design = AsyncMock()
        design.permits_unscheduled_visits = AsyncMock(return_value=False)
        visits = AsyncMock()
        service = _make_service(design_service=design, visits=visits)

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid.uuid4(),
            design_version_id=design_version_id,
            current_step=FlowStep.SUBJECT,
        )
        data = UnscheduledVisitCreate(name="Unscheduled follow-up")

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.create_unscheduled_visit(
                AsyncMock(), state, data, actor_id
            )

        assert "unscheduled" in exc_info.value.message.lower()
        # No visit persisted and the flow did not advance.
        visits.create_unscheduled.assert_not_awaited()
        assert state.current_step == FlowStep.SUBJECT
        assert state.visit_instance_id is None


# ---------------------------------------------------------------------------
# Step 4 — Form selection (R7.6)
# ---------------------------------------------------------------------------


class TestFormStep:
    async def test_select_form_requires_visit(self, study_id, site_id):
        """R7.8: cannot select a form before completing visit selection."""
        service = _make_service()
        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid.uuid4(),
            design_version_id=uuid.uuid4(),
            current_step=FlowStep.SUBJECT,
        )

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.select_form(AsyncMock(), state, uuid.uuid4())

        assert exc_info.value.details["incomplete_prior_step"] == "visit selection"
        assert state.current_step == FlowStep.SUBJECT

    async def test_select_form_reads_fields_from_design(self, study_id, site_id):
        """R7.6: field set is read from the bound design, not the operational store."""
        subject_id = uuid.uuid4()
        visit_instance_id = uuid.uuid4()
        design_version_id = uuid.uuid4()
        form_definition_id = uuid.uuid4()
        form_instance = SimpleNamespace(
            id=uuid.uuid4(),
            subject_id=subject_id,
            visit_instance_id=visit_instance_id,
            form_definition_id=form_definition_id,
        )
        field_ids = [uuid.uuid4(), uuid.uuid4()]
        design = AsyncMock()
        design.get_form_fields = AsyncMock(
            return_value=[SimpleNamespace(id=fid) for fid in field_ids]
        )
        service = _make_service(design_service=design)
        # Patch the private form-instance lookup to return our fake.
        service._get_form_instance = AsyncMock(return_value=form_instance)

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            design_version_id=design_version_id,
            visit_instance_id=visit_instance_id,
            current_step=FlowStep.VISIT,
        )

        session = AsyncMock()
        result = await service.select_form(session, state, form_instance.id)

        # Fields were read from the bound published design (consumption contract)
        # for the selected form definition.
        design.get_form_fields.assert_awaited_once_with(
            session, design_version_id, form_definition_id
        )
        assert result.form_instance_id == form_instance.id
        assert set(result.form_field_ids) == set(field_ids)
        assert result.current_step == FlowStep.FORM

    async def test_select_form_wrong_subject_rejected(self, study_id, site_id):
        form_instance = SimpleNamespace(
            id=uuid.uuid4(),
            subject_id=uuid.uuid4(),  # different subject
            visit_instance_id=uuid.uuid4(),
            form_definition_id=uuid.uuid4(),
        )
        service = _make_service()
        service._get_form_instance = AsyncMock(return_value=form_instance)

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid.uuid4(),
            design_version_id=uuid.uuid4(),
            visit_instance_id=uuid.uuid4(),
            current_step=FlowStep.VISIT,
        )

        with pytest.raises(BusinessRuleError):
            await service.select_form(AsyncMock(), state, form_instance.id)


# ---------------------------------------------------------------------------
# Step 5 — Data entry (R7.7)
# ---------------------------------------------------------------------------


class TestDataStep:
    async def test_enter_data_requires_form(self, study_id, site_id):
        """R7.8: cannot enter data before completing form selection."""
        service = _make_service()
        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid.uuid4(),
            design_version_id=uuid.uuid4(),
            visit_instance_id=uuid.uuid4(),
            current_step=FlowStep.VISIT,
        )

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.enter_data(AsyncMock(), state, {}, uuid.uuid4())

        assert exc_info.value.details["incomplete_prior_step"] == "form selection"
        assert state.current_step == FlowStep.VISIT

    async def test_enter_data_persists_via_data_capture(
        self, study_id, site_id, actor_id
    ):
        """R7.7: entered values persist as Operational_Records via data_capture."""
        field_id = uuid.uuid4()
        form_instance = SimpleNamespace(id=uuid.uuid4())
        updated = SimpleNamespace(id=form_instance.id)
        data_capture = AsyncMock()
        data_capture.load = AsyncMock(return_value=form_instance)
        data_capture.save_draft = AsyncMock(return_value=updated)
        service = _make_service(data_capture=data_capture)

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid.uuid4(),
            design_version_id=uuid.uuid4(),
            visit_instance_id=uuid.uuid4(),
            form_instance_id=form_instance.id,
            form_field_ids=(field_id,),
            current_step=FlowStep.FORM,
        )
        values = {str(field_id): "42"}

        result = await service.enter_data(AsyncMock(), state, values, actor_id)

        assert result is updated
        data_capture.save_draft.assert_awaited_once()
        assert state.current_step == FlowStep.DATA

    async def test_enter_data_rejects_field_outside_design(
        self, study_id, site_id, actor_id
    ):
        """R7.6/R7.7: values for fields outside the design's set are rejected."""
        design_field_id = uuid.uuid4()
        rogue_field_id = uuid.uuid4()
        data_capture = AsyncMock()
        service = _make_service(data_capture=data_capture)

        state = DataEntryFlowState(
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid.uuid4(),
            design_version_id=uuid.uuid4(),
            visit_instance_id=uuid.uuid4(),
            form_instance_id=uuid.uuid4(),
            form_field_ids=(design_field_id,),
            current_step=FlowStep.FORM,
        )
        values = {str(rogue_field_id): "nope"}

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.enter_data(AsyncMock(), state, values, actor_id)

        assert str(rogue_field_id) in exc_info.value.details["unknown_field_ids"]
        data_capture.save_draft.assert_not_awaited()
        assert state.current_step == FlowStep.FORM


# ---------------------------------------------------------------------------
# Step-ordering invariant across the whole flow (R7.8)
# ---------------------------------------------------------------------------


class TestStepOrderingInvariant:
    async def test_skipping_to_data_from_start_is_rejected(self, study_id):
        service = _make_service()
        state = service.start(study_id)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.enter_data(AsyncMock(), state, {}, uuid.uuid4())

        # The error identifies the immediate incomplete prior step (R7.8).
        assert exc_info.value.details["incomplete_prior_step"] == "form selection"
        assert state.current_step == FlowStep.START

    async def test_skipping_to_visit_from_start_is_rejected(self, study_id):
        service = _make_service()
        state = service.start(study_id)

        with pytest.raises(BusinessRuleError) as exc_info:
            await service.select_visit(AsyncMock(), state, uuid.uuid4())

        assert (
            exc_info.value.details["incomplete_prior_step"] == "subject selection"
        )
        assert state.current_step == FlowStep.START


class TestSingleton:
    def test_singleton_exists(self):
        assert data_entry_flow_service is not None
        assert isinstance(data_entry_flow_service, DataEntryFlowService)
