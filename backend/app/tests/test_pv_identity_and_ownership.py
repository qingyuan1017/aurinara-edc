"""Unit coverage for PV canonical identity resolution and ownership guards.

Feature: pv-safety-module, Task 2.1
Validates: Requirements 3.10, 16.6, 23.1, 23.2, 23.3, 23.4, 23.5, 23.9

Mirrors the CTMS identity/ownership tests. PV resolves canonical Study/Site and
the EDC Subject_Reference by stable UUID only, rejecting unknown, ambiguous, and
cross-scope references before any state change, and rejects PV commands that
carry an EDC-owned clinical field/operation or a CTMS-owned operational field.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pv import Module
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject
from app.services.pv_identity_service import (
    CanonicalEntityType,
    PVIdentityResolver,
)
from app.services.pv_ownership_guard import (
    PVOwnershipError,
    assert_pv_command_safe,
)


def _session_for(*rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# Canonical identity resolution (Requirements 23.1, 23.2, 23.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subject_reference_resolves_by_stable_id_and_records_metadata():
    study_id = uuid4()
    site_id = uuid4()
    subject_id = uuid4()
    subject = Subject(id=subject_id, study_id=study_id, site_id=site_id)
    resolver = PVIdentityResolver(_session_for(subject))

    resolved = await resolver.resolve_subject_reference(
        str(subject_id), study_id=study_id, site_id=site_id
    )
    metadata = resolved.reference_metadata(
        target_reference=uuid4(), ownership_rule_version=3, correlation_id="corr-1"
    )

    assert resolved.entity_type is CanonicalEntityType.SUBJECT
    assert resolved.id == subject_id
    assert resolved.source_identifier == subject_id
    # PV references the EDC clinical identity; the link targets PV.
    assert metadata.source_module is Module.EDC
    assert metadata.target_module is Module.PV
    assert metadata.ownership_rule_version == 3
    assert metadata.as_dict()["correlation_id"] == "corr-1"
    assert metadata.as_dict()["source_identifier"] == str(subject_id)


@pytest.mark.asyncio
async def test_study_resolution_returns_stable_identity():
    study_id = uuid4()
    resolver = PVIdentityResolver(_session_for(Study(id=study_id)))
    resolved = await resolver.resolve_study(study_id)
    assert resolved.entity_type is CanonicalEntityType.STUDY
    assert resolved.id == study_id


@pytest.mark.asyncio
async def test_resolution_rejects_display_name_unknown_and_ambiguous_references():
    subject_id = uuid4()

    with pytest.raises(ValidationError) as display_error:
        await PVIdentityResolver(_session_for()).resolve_subject_reference("Subject 1")
    assert display_error.value.details["reason"] == "DISPLAY_NAME_NOT_ALLOWED"

    with pytest.raises(NotFoundError) as missing_error:
        await PVIdentityResolver(_session_for()).resolve_subject_reference(subject_id)
    assert missing_error.value.details["reason"] == "RECORD_NOT_FOUND"

    first = Subject(id=subject_id, study_id=uuid4(), site_id=uuid4())
    second = Subject(id=subject_id, study_id=uuid4(), site_id=uuid4())
    with pytest.raises(ConflictError) as ambiguous_error:
        await PVIdentityResolver(_session_for(first, second)).resolve(
            CanonicalEntityType.SUBJECT, subject_id
        )
    assert ambiguous_error.value.details["reason"] == "AMBIGUOUS_REFERENCE"


@pytest.mark.asyncio
async def test_resolution_rejects_cross_scope_references_without_mutating_session():
    site_id = uuid4()
    site = Site(id=site_id, study_id=uuid4(), site_number="001", name="Site A")
    session = _session_for(site)

    with pytest.raises(ConflictError) as error:
        await PVIdentityResolver(session).resolve_site(site_id, study_id=uuid4())

    assert error.value.details["reason"] == "REFERENCE_SCOPE_MISMATCH"
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Ownership guards (Requirements 16.6, 23.4, 23.5, 3.10)
# ---------------------------------------------------------------------------


def test_ownership_guard_allows_read_only_canonical_references():
    assert_pv_command_safe(
        {
            "study_id": uuid4(),
            "site_id": uuid4(),
            "subject_reference": uuid4(),
            "visit_instance_id": uuid4(),
            "case_type": "Adverse Event",
            "verbatim_term": "headache",
            "correlation_id": "corr-1",
        },
        operation="create_case",
    )


@pytest.mark.parametrize(
    ("operation", "payload", "field", "module"),
    [
        ("create_subject", {}, "create_subject", "EDC"),
        ("allocate_subject_identifier", {}, "allocate_subject_identifier", "EDC"),
        ("create_visit_instance", {}, "create_visit_instance", "EDC"),
        ("create_case", {"study_version_id": uuid4()}, "$.study_version_id", "EDC"),
        ("create_case", {"subject": {"subject_number": "S-1"}}, "$.subject", "EDC"),
        ("create_case", {"nested": {"field_values": ["x"]}}, "$.nested.field_values", "EDC"),
        ("record_assessment", {"query_status": "Closed"}, "$.query_status", "EDC"),
        ("add_adverse_event", {"lock_status": "Locked"}, "$.lock_status", "EDC"),
        ("upload_attachment", {"clinical_attachment": {"key": "s"}}, "$.clinical_attachment", "EDC"),
        ("create_case", {"clinical_export": {"id": uuid4()}}, "$.clinical_export", "EDC"),
    ],
)
def test_ownership_guard_rejects_edc_owned_before_state_change(
    operation, payload, field, module
):
    with pytest.raises(PVOwnershipError) as error:
        assert_pv_command_safe(payload, operation=operation)

    assert error.value.details["field"] == field
    assert error.value.details["authoritative_module"] == module
    assert error.value.details["reason"] == "EDC_OWNERSHIP_VIOLATION"
    assert error.value.code == "PV_OWNERSHIP_CONFLICT"


@pytest.mark.parametrize(
    ("operation", "payload", "field"),
    [
        ("update_enrollment", {}, "update_enrollment"),
        ("schedule_monitoring_activity", {}, "schedule_monitoring_activity"),
        ("create_case", {"monitoring_plan": {"id": uuid4()}}, "$.monitoring_plan"),
        ("create_case", {"enrollment_target": 100}, "$.enrollment_target"),
        ("upload_attachment", {"operational_attachment": {"k": "v"}}, "$.operational_attachment"),
    ],
)
def test_ownership_guard_rejects_ctms_owned_before_state_change(
    operation, payload, field
):
    with pytest.raises(PVOwnershipError) as error:
        assert_pv_command_safe(payload, operation=operation)

    assert error.value.details["field"] == field
    assert error.value.details["authoritative_module"] == "CTMS"
    assert error.value.details["reason"] == "CTMS_OWNERSHIP_VIOLATION"


@pytest.mark.parametrize(
    "operation",
    ["create_visit_instance", "update_field_value", "lock_clinical_record", "create_subject"],
)
def test_competing_clinical_operations_are_rejected_even_without_payload(operation):
    with pytest.raises(PVOwnershipError) as error:
        assert_pv_command_safe({}, operation=operation)
    assert error.value.details["authoritative_module"] == "EDC"
