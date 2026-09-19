"""Unit coverage for CTMS canonical references and EDC ownership guards."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.site import Site
from app.services.ctms_identity_service import (
    CanonicalEntityType,
    CanonicalIdentityResolver,
)
from app.services.ctms_ownership_guard import (
    CTMSOwnershipError,
    assert_ctms_command_safe,
)


def _session_for(*rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_site_resolution_uses_stable_id_and_preserves_link_metadata():
    study_id = uuid4()
    site_id = uuid4()
    site = Site(id=site_id, study_id=study_id, site_number="001", name="Site A")
    resolver = CanonicalIdentityResolver(_session_for(site))

    resolved = await resolver.resolve_site(str(site_id), study_id=study_id)
    metadata = resolved.link_metadata(
        target_reference=uuid4(), ownership_rule_version=7, correlation_id="corr-1"
    )

    assert resolved.id == site_id
    assert resolved.source_identifier == site_id
    assert metadata.source_module is Module.EDC
    assert metadata.target_module is Module.CTMS
    assert metadata.ownership_rule_version == 7
    assert metadata.as_dict()["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_resolution_rejects_display_name_unknown_and_ambiguous_references():
    site_id = uuid4()
    resolver = CanonicalIdentityResolver(_session_for())

    with pytest.raises(ValidationError) as display_error:
        await resolver.resolve_site("Site A")
    assert display_error.value.details["reason"] == "DISPLAY_NAME_NOT_ALLOWED"

    with pytest.raises(NotFoundError) as missing_error:
        await resolver.resolve_site(site_id)
    assert missing_error.value.details["reason"] == "RECORD_NOT_FOUND"

    first = Site(id=site_id, study_id=uuid4(), site_number="001", name="Site A")
    second = Site(id=site_id, study_id=uuid4(), site_number="002", name="Site B")
    ambiguous = CanonicalIdentityResolver(_session_for(first, second))
    with pytest.raises(ConflictError) as ambiguous_error:
        await ambiguous.resolve(CanonicalEntityType.SITE, site_id)
    assert ambiguous_error.value.details["reason"] == "AMBIGUOUS_REFERENCE"


@pytest.mark.asyncio
async def test_resolution_rejects_cross_scope_references_without_mutating_session():
    site_id = uuid4()
    site = Site(id=site_id, study_id=uuid4(), site_number="001", name="Site A")
    session = _session_for(site)

    with pytest.raises(ConflictError) as error:
        await CanonicalIdentityResolver(session).resolve_site(site_id, study_id=uuid4())

    assert error.value.details["reason"] == "REFERENCE_SCOPE_MISMATCH"
    session.add.assert_not_called()


def test_ownership_guard_allows_read_only_canonical_ids():
    assert_ctms_command_safe(
        {
            "study_id": uuid4(),
            "site_id": uuid4(),
            "subject_id": uuid4(),
            "edc_visit_instance_id": uuid4(),
            "source_query_id": uuid4(),
            "correlation_id": "corr-1",
        },
        operation="record_operational_milestone",
    )


@pytest.mark.parametrize(
    ("operation", "payload", "field"),
    [
        ("create_subject", {}, "create_subject"),
        ("schedule_monitoring_activity", {"study_version_id": uuid4()}, "$.study_version_id"),
        ("record_operational_milestone", {"subject": {"subject_number": "S-1"}}, "$.subject"),
        ("record_operational_milestone", {"nested": {"field_values": ["secret"]}}, "$.nested.field_values"),
        ("create_query_follow_up", {"query_status": "Closed"}, "$.query_status"),
        ("schedule_monitoring_activity", {"lock_status": "Locked"}, "$.lock_status"),
        ("create_task", {"clinical_attachment": {"storage_key": "secret"}}, "$.clinical_attachment"),
    ],
)
def test_ownership_guard_rejects_clinical_mutations_before_state_change(
    operation, payload, field
):
    with pytest.raises(CTMSOwnershipError) as error:
        assert_ctms_command_safe(payload, operation=operation)

    assert error.value.details["field"] == field
    assert error.value.details["authoritative_module"] == "EDC"


@pytest.mark.parametrize("operation", ["create_visit_instance", "update_field_value", "lock_clinical_record"])
def test_competing_clinical_operations_are_rejected_even_without_payload(operation):
    with pytest.raises(CTMSOwnershipError):
        assert_ctms_command_safe({}, operation=operation)
