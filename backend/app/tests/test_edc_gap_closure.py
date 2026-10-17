"""Focused regression tests for the core EDC gap-closure foundation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import BusinessRuleError
from app.models.edc.operations import (
    ClinicalControlRequest,
    ClinicalControlRequestStatus,
)
from app.schemas.edc.operations import (
    EDCCapabilities,
    FormOperationalStatus,
    SDRSettingUpsert,
)
from app.services.edc.clinical_control_service import ClinicalControlService
from app.services.edc.operational_service import EDCOperationalService
from app.services.edc.revision_service import ClinicalRevisionService
from app.services.edc.subject_service import SubjectService


def test_capability_manifest_explicitly_disables_medical_coding():
    capabilities = EDCCapabilities()

    assert capabilities.medical_coding is False
    assert capabilities.sdr is True
    assert capabilities.controlled_lock is True


@pytest.mark.parametrize(
    "payload",
    [
        {"strategy": "percentage"},
        {"strategy": "targeted", "targeted_field_ids": []},
    ],
)
def test_sdr_strategy_requires_reproducible_selection_inputs(payload):
    with pytest.raises(ValidationError):
        SDRSettingUpsert.model_validate(payload)


def test_revision_bump_is_monotonic_and_propagates_to_ancestors():
    subject = SimpleNamespace(data_revision=8)
    visit = SimpleNamespace(data_revision=5)
    field = SimpleNamespace(data_revision=2)
    form = SimpleNamespace(
        data_revision=3,
        visit_instance=visit,
        subject=subject,
    )

    result = ClinicalRevisionService.bump_form(form, field_value=field)

    assert result == 4
    assert field.data_revision == 3
    assert visit.data_revision == 6
    assert subject.data_revision == 9


def test_operational_status_keeps_workflows_independent():
    status = FormOperationalStatus(
        data_entry="Submitted",
        review="Stale",
        sdv="Verified",
        sdr="In Review",
        freeze="Active",
        lock="Inactive",
        signature="Stale",
        active_query_count=2,
        data_revision=7,
    )

    assert status.data_entry == "Submitted"
    assert status.review == "Stale"
    assert status.sdv == "Verified"
    assert status.sdr == "In Review"
    assert status.signature == "Stale"


async def test_subject_enrollment_readiness_reports_all_prerequisites():
    version_result = MagicMock()
    version_result.scalars.return_value.first.return_value = None
    site_count_result = MagicMock()
    site_count_result.scalar_one.return_value = 0
    session = AsyncMock()
    session.execute.side_effect = [version_result, site_count_result]

    readiness = await SubjectService().enrollment_readiness(session, uuid4())

    assert readiness["ready"] is False
    assert readiness["published_version_id"] is None
    assert readiness["authorized_active_site_count"] == 0
    assert {blocker["code"] for blocker in readiness["blockers"]} == {
        "NO_PUBLISHED_DESIGN",
        "NO_AUTHORIZED_ACTIVE_SITE",
    }


async def test_requester_cannot_approve_own_control_request():
    actor_id = uuid4()
    request = ClinicalControlRequest(
        id=uuid4(),
        study_id=uuid4(),
        scope_type="study",
        scope_id=uuid4(),
        action="lock",
        status=ClinicalControlRequestStatus.pending_approval.value,
        reason="Database lock",
        requested_by=actor_id,
    )
    service = ClinicalControlService()
    session = AsyncMock()

    with (
        patch.object(service, "_get", AsyncMock(return_value=request)),
        pytest.raises(BusinessRuleError, match="cannot approve"),
    ):
        await service.approve(session, request.id, actor_id)

    session.flush.assert_not_awaited()


async def test_independent_approver_records_decision_and_audit():
    requester_id = uuid4()
    approver_id = uuid4()
    request = ClinicalControlRequest(
        id=uuid4(),
        study_id=uuid4(),
        scope_type="study",
        scope_id=uuid4(),
        action="lock",
        status=ClinicalControlRequestStatus.pending_approval.value,
        reason="Database lock",
        requested_by=requester_id,
    )
    service = ClinicalControlService()
    session = AsyncMock()

    with (
        patch.object(service, "_get", AsyncMock(return_value=request)),
        patch.object(service, "_audit", AsyncMock()) as audit,
    ):
        result = await service.approve(session, request.id, approver_id)

    assert result.status == ClinicalControlRequestStatus.approved.value
    assert result.approved_by == approver_id
    assert result.approved_at is not None
    session.flush.assert_awaited_once()
    audit.assert_awaited_once_with(session, request, "approve", approver_id)


async def test_listing_field_access_uses_most_specific_role_grant():
    design_version_id = uuid4()
    form_id = uuid4()
    visible_field = SimpleNamespace(id=uuid4())
    denied_field = SimpleNamespace(id=uuid4())
    definition = SimpleNamespace(id=form_id, study_version_id=design_version_id)
    default_grant = SimpleNamespace(
        role="Data Manager",
        form_definition_id=None,
        field_definition_id=None,
        can_read=True,
        blinded=False,
        unblind_role=None,
    )
    field_denial = SimpleNamespace(
        role="Data Manager",
        form_definition_id=form_id,
        field_definition_id=denied_field.id,
        can_read=False,
        blinded=False,
        unblind_role=None,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.all.return_value = [default_grant, field_denial]
    session = AsyncMock()
    session.execute.return_value = query_result

    readable = await EDCOperationalService.readable_fields(
        session,
        definition,
        [visible_field, denied_field],
        {"Data Manager"},
    )

    assert readable == [visible_field]
