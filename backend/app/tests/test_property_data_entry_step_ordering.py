"""Property-based test for the Data_Entry_Flow step-ordering invariant.

# Feature: designer-edc-refactor, Property 6: Data-entry step-ordering invariant

Property 6 (design.md): For all Data_Entry_Flow states and all attempts to
advance to a later step before the required prior step is complete, the advance
is rejected, the current step is retained, and the error identifies the
incomplete prior step; selectable sites, forms, and fields at each step are
always a subset of the user's scope and the bound Published_Design.

The state machine under test is ``DataEntryFlowService`` in
``app/services/edc/data_entry_flow_service.py`` with the ordered ``FlowStep``
sequence START -> SITE -> SUBJECT -> VISIT -> FORM -> DATA.

This test drives the service with *random sequences* of the five flow
operations (``select_site``, ``select_subject``/``add_subject``,
``select_visit``/``create_unscheduled_visit``, ``select_form``,
``enter_data``). For each attempted operation:

* If its required prior step is **not** yet complete, the operation must raise a
  ``BusinessRuleError`` that identifies the incomplete prior step, and
  ``state.current_step`` must be left unchanged (the flow does not advance).
* If its required prior step **is** complete, the operation succeeds and
  ``state.current_step`` advances monotonically to that step's value.

Collaborators are mocked with ``AsyncMock`` (mirroring the unit-test fakes) so
each in-order operation resolves deterministically with no database.

**Validates: Requirements 7.1, 7.2, 7.4, 7.6, 7.7, 7.8**
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError
from app.services.edc.data_entry_flow_service import (
    DataEntryFlowService,
    FlowStep,
)

# ---------------------------------------------------------------------------
# Flow operations
# ---------------------------------------------------------------------------

# The five operation kinds, each keyed to the FlowStep it advances the flow to
# and the required prior step whose absence must trigger rejection. The two
# "variant" operations (add_subject / create_unscheduled_visit) exercise the
# alternative transition into the SUBJECT and VISIT steps.
_OPERATIONS = (
    "select_site",
    "select_subject",
    "add_subject",
    "select_visit",
    "create_unscheduled_visit",
    "select_form",
    "enter_data",
)

# target step reached on success, and the human label of the prior step the
# guard reports when it is incomplete (mirrors _STEP_LABELS in the service).
_TARGET_STEP = {
    "select_site": FlowStep.SITE,
    "select_subject": FlowStep.SUBJECT,
    "add_subject": FlowStep.SUBJECT,
    "select_visit": FlowStep.VISIT,
    "create_unscheduled_visit": FlowStep.VISIT,
    "select_form": FlowStep.FORM,
    "enter_data": FlowStep.DATA,
}

_REQUIRED_PRIOR_LABEL = {
    "select_subject": "site selection",
    "add_subject": "site selection",
    "select_visit": "subject selection",
    "create_unscheduled_visit": "subject selection",
    "select_form": "visit selection",
    "enter_data": "form selection",
}

# A random, possibly-redundant sequence of operations. Lists are allowed to
# repeat and to omit operations so out-of-order attempts are frequently
# generated.
_operation_sequences = st.lists(
    st.sampled_from(_OPERATIONS), min_size=1, max_size=20
)


# ---------------------------------------------------------------------------
# Fixed identifiers / fakes shared across one flow run
# ---------------------------------------------------------------------------


def _build_fixture() -> dict[str, object]:
    """Create a service wired with AsyncMock collaborators and shared ids.

    Every collaborator returns an object consistent with the flow state so that
    an *in-order* operation always succeeds. The returned dict carries the ids
    the operations must pass to keep the collaborators' ownership checks happy.
    """
    study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    design_version_id = uuid.uuid4()
    visit_instance_id = uuid.uuid4()
    form_instance_id = uuid.uuid4()
    form_definition_id = uuid.uuid4()
    field_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    user = SimpleNamespace(id=uuid.uuid4())

    subject = SimpleNamespace(
        id=subject_id,
        study_id=study_id,
        site_id=site_id,
        study_version_id=design_version_id,
    )
    visit_instance = SimpleNamespace(id=visit_instance_id, subject_id=subject_id)
    form_instance = SimpleNamespace(
        id=form_instance_id,
        subject_id=subject_id,
        visit_instance_id=visit_instance_id,
        form_definition_id=form_definition_id,
    )

    # Permission fake passes every candidate site through (in scope — R7.1).
    permissions = MagicMock()
    permissions.filter_sites = MagicMock(
        side_effect=lambda u, ids, mapping=None: list(ids)
    )

    design = AsyncMock()
    design.permits_unscheduled_visits = AsyncMock(return_value=True)
    design.get_form_fields = AsyncMock(
        return_value=[SimpleNamespace(id=field_id)]
    )

    subjects = AsyncMock()
    subjects.get_subject = AsyncMock(return_value=subject)
    subjects.create_subject = AsyncMock(return_value=subject)

    visits = AsyncMock()
    visits.get_instance = AsyncMock(return_value=visit_instance)
    visits.create_unscheduled = AsyncMock(return_value=visit_instance)

    data_capture = AsyncMock()
    data_capture.load = AsyncMock(return_value=form_instance)
    data_capture.save_draft = AsyncMock(
        return_value=SimpleNamespace(id=form_instance_id)
    )

    service = DataEntryFlowService(
        permission_service=permissions,
        design_service=design,
        subjects=subjects,
        visits=visits,
        data_capture=data_capture,
    )

    # A session mock whose execute() returns the shared site / form instance for
    # the service's internal lookups (_get_site, _get_form_instance).
    def _make_session(return_value: object) -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = return_value
        session.execute = AsyncMock(return_value=result)
        return session

    site = SimpleNamespace(id=site_id, study_id=study_id)

    return {
        "service": service,
        "state": service.start(study_id),
        "user": user,
        "actor_id": actor_id,
        "ids": SimpleNamespace(
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            visit_instance_id=visit_instance_id,
            form_instance_id=form_instance_id,
            field_id=field_id,
        ),
        "site_session": _make_session(site),
        "form_session": _make_session(form_instance),
    }


async def _invoke(op: str, fx: dict[str, object]):
    """Dispatch one flow operation using the shared fixture collaborators."""
    service: DataEntryFlowService = fx["service"]  # type: ignore[assignment]
    state = fx["state"]
    ids = fx["ids"]
    actor_id = fx["actor_id"]

    if op == "select_site":
        return await service.select_site(
            fx["site_session"], state, fx["user"], ids.site_id
        )
    if op == "select_subject":
        return await service.select_subject(AsyncMock(), state, ids.subject_id)
    if op == "add_subject":
        from app.schemas.edc.subject import SubjectCreate

        return await service.add_subject(
            AsyncMock(), state, SubjectCreate(site_id=ids.site_id), actor_id
        )
    if op == "select_visit":
        return await service.select_visit(
            AsyncMock(), state, ids.visit_instance_id
        )
    if op == "create_unscheduled_visit":
        from app.schemas.edc.visit import UnscheduledVisitCreate

        return await service.create_unscheduled_visit(
            AsyncMock(), state, UnscheduledVisitCreate(name="Unscheduled"), actor_id
        )
    if op == "select_form":
        return await service.select_form(
            fx["form_session"], state, ids.form_instance_id
        )
    if op == "enter_data":
        return await service.enter_data(
            AsyncMock(), state, {str(ids.field_id): "value"}, actor_id
        )
    raise AssertionError(f"unknown operation {op}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Property 6
# ---------------------------------------------------------------------------


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(sequence=_operation_sequences)
async def test_data_entry_step_ordering_invariant(sequence: list[str]):
    """Out-of-order flow ops are rejected and retain the step; in-order ops advance.

    For any random sequence of attempted operations the flow enforces strict
    step ordering: an operation whose required prior step is incomplete is
    rejected with a ``BusinessRuleError`` identifying that incomplete prior step
    and leaves ``current_step`` unchanged, while an operation performed in order
    advances ``current_step`` monotonically along
    START -> SITE -> SUBJECT -> VISIT -> FORM -> DATA.

    **Validates: Requirements 7.1, 7.2, 7.4, 7.6, 7.7, 7.8**
    """
    fx = _build_fixture()
    state = fx["state"]
    assert state.current_step == FlowStep.START

    for op in sequence:
        target = _TARGET_STEP[op]
        step_before = state.current_step

        # The guard requires the step immediately before the target to be
        # complete. select_site has no prior step and is always permitted.
        prior_complete = step_before >= (target - 1)

        if prior_complete:
            await _invoke(op, fx)
            # An op whose required prior step is complete succeeds and leaves the
            # flow exactly at that op's target step. (Re-performing an already
            # satisfied step — e.g. re-selecting the site — is permitted and sets
            # the step to that target; it is not an ordering violation.)
            assert state.current_step == target
        else:
            with pytest.raises(BusinessRuleError) as exc_info:
                await _invoke(op, fx)
            # The error identifies the incomplete prior step (R7.8)...
            assert (
                exc_info.value.details["incomplete_prior_step"]
                == _REQUIRED_PRIOR_LABEL[op]
            )
            # ...and the current step is retained (no mutation on rejection).
            assert state.current_step == step_before


# A correctly ordered run: one representative operation per step, in order. The
# two SUBJECT/VISIT variants are each exercised as an alternative in-order path.
_ordered_runs = st.tuples(
    st.sampled_from(("select_subject", "add_subject")),
    st.sampled_from(("select_visit", "create_unscheduled_visit")),
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(variants=_ordered_runs)
async def test_in_order_run_advances_monotonically(variants: tuple[str, str]):
    """A correctly ordered run advances START -> SITE -> SUBJECT -> VISIT -> FORM -> DATA.

    Performing each step in order advances ``current_step`` strictly upward
    through every ``FlowStep`` with no rejection, covering both the
    select/add-subject and select/create-unscheduled-visit transition variants.

    **Validates: Requirements 7.1, 7.2, 7.4, 7.6, 7.7, 7.8**
    """
    subject_op, visit_op = variants
    fx = _build_fixture()
    state = fx["state"]

    ordered = ["select_site", subject_op, visit_op, "select_form", "enter_data"]
    expected_steps = [
        FlowStep.SITE,
        FlowStep.SUBJECT,
        FlowStep.VISIT,
        FlowStep.FORM,
        FlowStep.DATA,
    ]

    previous = FlowStep.START
    for op, expected in zip(ordered, expected_steps, strict=True):
        await _invoke(op, fx)
        # Each in-order op advances to its target and strictly upward.
        assert state.current_step == expected
        assert state.current_step > previous
        previous = state.current_step

    assert state.current_step == FlowStep.DATA
