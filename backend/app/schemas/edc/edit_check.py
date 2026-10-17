"""Pydantic schemas for declarative edit checks.

The rule payload remains JSON-shaped at the API boundary.  The edit-check
service validates it with ``app.core.edit_check_dsl.validate_rule`` before
persistence and runtime evaluation, keeping the DSL validator as the single
source of truth across routes and services.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.models.edc.edit_check import EditCheck
from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    UtcDatetime,
)


class EditCheckCreate(BaseCreateSchema):
    """Create an edit check on a draft study version."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=4000)
    rule_json: dict[str, Any]
    severity: str = Field(..., pattern=r"^(info|warning|error|query)$")
    is_active: bool = True
    needs_retesting: bool = False
    retesting_reason: str | None = Field(None, max_length=4000)


class EditCheckUpdate(BaseUpdateSchema):
    """Partial update for an edit check; rules are revalidated if supplied."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=4000)
    rule_json: dict[str, Any] | None = None
    severity: str | None = Field(None, pattern=r"^(info|warning|error|query)$")
    is_active: bool | None = None
    needs_retesting: bool | None = None
    retesting_reason: str | None = Field(None, max_length=4000)


class EditCheckResponse(BaseSchema):
    """Serialized edit-check response."""

    id: UUID
    odm_oid: str | None = None
    study_version_id: UUID
    name: str
    description: str | None = None
    rule_json: dict[str, Any]
    severity: str
    is_active: bool
    schema_version: int = 1
    needs_retesting: bool = False
    retesting_reason: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


# Make the imported model visible for consumers that build responses directly
# from ORM records without needing an additional import.
__all__ = [
    "EditCheck",
    "EditCheckBulkRetestRequest",
    "EditCheckBulkRetestResponse",
    "EditCheckCreate",
    "EditCheckResponse",
    "EditCheckRetestRequest",
    "EditCheckRetestResponse",
    "EditCheckRunRequest",
    "EditCheckRunResponse",
    "EditCheckTestRequest",
    "EditCheckTestResponse",
    "EditCheckUpdate",
    "ValidationResultResponse",
]


class EditCheckTestRequest(BaseCreateSchema):
    """Sample data used to test a rule without touching clinical data."""

    sample_data: dict[str, Any] = Field(default_factory=dict)


class EditCheckTestResponse(BaseSchema):
    """The deterministic result of a non-persistent edit-check test."""

    edit_check_id: UUID
    outcome: bool
    matched: bool
    passed: bool
    persisted: bool = False


class EditCheckRetestRequest(BaseCreateSchema):
    """Evidence and reviewer attestation used to clear a retesting hold."""

    sample_data: dict[str, Any] = Field(default_factory=dict)
    expected_matched: bool
    review_note: str = Field(..., min_length=1, max_length=4000)


class EditCheckRetestResponse(BaseSchema):
    """Result of a successful, audited edit-check retest."""

    edit_check_id: UUID
    outcome: bool
    matched: bool
    passed: bool
    persisted: bool = False
    needs_retesting: bool = False


class EditCheckBulkRetestRequest(BaseCreateSchema):
    """Explicit attestation for bulk clearing validated retesting holds."""

    review_note: str = Field(..., min_length=1, max_length=4000)
    acknowledge_without_individual_samples: Literal[True]


class EditCheckBulkRetestResponse(BaseSchema):
    """Summary of an atomic bulk retesting attestation."""

    study_version_id: UUID
    reviewed_count: int = Field(..., ge=0)
    remaining_count: int = Field(..., ge=0)


class EditCheckRunRequest(BaseCreateSchema):
    """Optional scope for a runtime evaluation run.

    With no IDs, all form instances in the selected study/version are checked.
    ``form_instance_id`` is accepted as a convenient single-form shorthand.
    """

    study_version_id: UUID | None = None
    form_instance_ids: list[UUID] = Field(default_factory=list)
    form_instance_id: UUID | None = None


class ValidationResultResponse(BaseSchema):
    """A failed edit-check result produced by a runtime run."""

    id: UUID
    edit_check_id: UUID
    form_instance_id: UUID
    severity: str
    outcome: str
    record_id: UUID | None = None
    field_definition_id: UUID | None = None
    message: str
    is_resolved: bool
    created_at: UtcDatetime


class EditCheckRunResponse(BaseSchema):
    """Summary of a runtime evaluation run."""

    study_id: UUID
    study_version_id: UUID | None = None
    evaluated_form_instances: int
    failed_checks: int
    results: list[ValidationResultResponse] = Field(default_factory=list)
