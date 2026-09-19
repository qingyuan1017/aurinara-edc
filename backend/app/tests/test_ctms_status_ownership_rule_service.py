"""Focused tests for CTMS ownership-rule compilation and minimization."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.ctms import Module
from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType, StatusOwnershipRule
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.status_ownership_rule_service import (
    StatusOwnershipRuleService,
)


class _Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.added = []

    async def execute(self, statement):
        return _Result(self.rows)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


def _create(**overrides):
    values = {
        "entity_type": "Subject",
        "field_path": "status",
        "authoritative_module": Module.EDC,
        "writable_module": Module.EDC,
        "projection_target": Module.CTMS,
        "projection_type": ProjectionType.SUBJECT_STATUS,
        "typed_allowlist": {
            "subject_id": ProjectionFieldType.UUID,
            "status": ProjectionFieldType.STRING,
            "source_version": ProjectionFieldType.STRING,
        },
        "version": 1,
        "effective_from": datetime(2025, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return StatusOwnershipRuleCreate(**values)


def test_typed_subject_projection_is_minimized_and_normalized():
    service = StatusOwnershipRuleService()
    compiled = service.compile_rule(_create().model_dump())
    subject_id = uuid4()

    result = service.validate_payload(
        compiled,
        {
            "subject_id": subject_id,
            "status": "Enrolled",
            "source_version": "edc-v3",
        },
    )

    assert result.accepted is True
    assert result.payload == {
        "subject_id": str(subject_id),
        "status": "Enrolled",
        "source_version": "edc-v3",
    }
    assert len(result.fingerprint) == 64


def test_projection_rejects_clinical_and_unknown_fields_without_retaining_values():
    service = StatusOwnershipRuleService()
    compiled = service.compile_rule(_create().model_dump())

    with pytest.raises(ValidationError) as error:
        service.validate_payload(
            compiled,
            {
                "status": "Enrolled",
                "clinical_data": {"value": "secret clinical value"},
                "nested": {"unknown": "not approved"},
            },
        )

    assert error.value.details["reason"] == "PROJECTION_FIELD_NOT_ALLOWED"
    assert "secret clinical value" not in str(error.value.details)


def test_conflicting_authority_is_rejected():
    with pytest.raises(ConflictError) as error:
        StatusOwnershipRuleService.compile_rule(
            {
                **_create().model_dump(),
                "writable_module": Module.CTMS,
            }
        )

    assert error.value.details["reason"] == "CONFLICTING_OWNERSHIP_RULE"


@pytest.mark.asyncio
async def test_rule_persistence_records_version_metadata_and_audit():
    service = StatusOwnershipRuleService()
    session = _Session()
    actor_id = uuid4()

    rule = await service.create_rule(
        session,
        _create(),
        actor_id,
        correlation_id="corr-rule-1",
    )

    assert rule.entity_type == "Subject"
    assert rule.field_path == "status"
    assert rule.authoritative_module == Module.EDC.value
    assert rule.writable_module == Module.EDC.value
    assert rule.projection_target == Module.CTMS.value
    assert rule.version == 1
    assert rule.correlation_id == "corr-rule-1"
    assert rule.allowlist_json["subject_id"] == ProjectionFieldType.UUID.value
    assert any(item.__class__.__name__ == "AuditEvent" for item in session.added)


@pytest.mark.asyncio
async def test_current_rule_rejects_same_version_ambiguity():
    effective = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [
        StatusOwnershipRule(
            entity_type="Subject",
            field_path="status",
            authoritative_module="EDC",
            writable_module="EDC",
            projection_target="CTMS",
            projection_type="subject_status",
            allowed_transitions={},
            allowlist_json={"status": "string"},
            version=2,
            effective_from=effective,
            status=OwnershipRuleStatus.ACTIVE,
            correlation_id="a",
        ),
        StatusOwnershipRule(
            entity_type="Subject",
            field_path="status",
            authoritative_module="EDC",
            writable_module="EDC",
            projection_target="CTMS",
            projection_type="subject_status",
            allowed_transitions={},
            allowlist_json={"status": "string"},
            version=2,
            effective_from=effective + timedelta(minutes=1),
            status=OwnershipRuleStatus.ACTIVE,
            correlation_id="b",
        ),
    ]

    with pytest.raises(ConflictError) as error:
        await StatusOwnershipRuleService().current_rule(
            _Session(rows), "Subject", "status", at=effective + timedelta(days=1)
        )

    assert error.value.details["reason"] == "AMBIGUOUS_OWNERSHIP_RULE"
