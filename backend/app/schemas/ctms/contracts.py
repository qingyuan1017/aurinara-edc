"""Public CTMS API vocabulary and sanitized error contracts.

These types are intentionally transport-facing.  They make ownership,
coordination, projection, failure, and pagination states discoverable in the
same OpenAPI document as the CTMS routes without exposing event payloads.
"""

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType
from app.models.ctms.projection import ProjectionStatus
from app.schemas.base import BaseSchema, ErrorBody, ErrorEnvelope


class CoordinationEventType(StrEnum):
    """Published event categories crossing an approved module boundary."""

    OPERATIONAL_STUDY_CHANGED = "CTMS_OPERATIONAL_STUDY_CHANGED"
    OPERATIONAL_SITE_CHANGED = "CTMS_OPERATIONAL_SITE_CHANGED"
    ENROLLMENT_TARGET_CHANGED = "CTMS_ENROLLMENT_TARGET_CHANGED"
    OPERATIONAL_MILESTONE_CHANGED = "CTMS_OPERATIONAL_MILESTONE_CHANGED"
    MONITORING_PLAN_CHANGED = "CTMS_MONITORING_PLAN_CHANGED"
    MONITORING_ACTIVITY_CHANGED = "CTMS_MONITORING_ACTIVITY_CHANGED"
    OPERATIONAL_TASK_CHANGED = "CTMS_OPERATIONAL_TASK_CHANGED"
    OPERATIONAL_CONTACT_CHANGED = "CTMS_OPERATIONAL_CONTACT_CHANGED"
    PROJECTION_UPDATED = "CTMS_PROJECTION_UPDATED"
    COORDINATED_TRANSITION = "CTMS_COORDINATED_TRANSITION"


class CoordinationEventStatus(StrEnum):
    """Durable lifecycle states of a coordination event."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    SKIPPED_CURRENT = "skipped_current"
    RETRYING = "retrying"
    FAILED = "failed"
    CONFLICT = "conflict"
    REPLAY_PENDING = "replay_pending"


class CoordinationFailureCode(StrEnum):
    """Non-retryable or terminal coordination failure categories."""

    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    OWNERSHIP_VIOLATION = "OWNERSHIP_VIOLATION"
    DATA_MINIMIZATION_FAILED = "DATA_MINIMIZATION_FAILED"
    PROJECTION_FIELD_NOT_ALLOWED = "PROJECTION_FIELD_NOT_ALLOWED"
    RETRY_LIMIT_EXCEEDED = "RETRY_LIMIT_EXCEEDED"
    RETRYABLE_STORAGE_ERROR = "RETRYABLE_STORAGE_ERROR"
    REFERENCE_SCOPE_MISMATCH = "REFERENCE_SCOPE_MISMATCH"


class CoordinationConflictCode(StrEnum):
    """Conflict categories that require policy-aware remediation."""

    OWNERSHIP_CONFLICT = "OWNERSHIP_CONFLICT"
    COORDINATION_CONFLICT = "COORDINATION_CONFLICT"
    OUT_OF_ORDER = "COORDINATION_OUT_OF_ORDER"
    STALE_PROJECTION = "STALE_PROJECTION"
    CONFLICTING_OWNERSHIP_RULE = "CONFLICTING_OWNERSHIP_RULE"
    PROJECTION_TARGET_MISMATCH = "PROJECTION_TARGET_NOT_CTMS"


class CTMSErrorCode(StrEnum):
    """Stable API error codes used by CTMS routes and coordination APIs."""

    CTMS_SCOPE_DENIED = "CTMS_SCOPE_DENIED"
    CTMS_RECORD_NOT_FOUND = "CTMS_RECORD_NOT_FOUND"
    CTMS_DUPLICATE_RECORD = "CTMS_DUPLICATE_RECORD"
    CTMS_INVALID_TRANSITION = "CTMS_INVALID_TRANSITION"
    CTMS_PLAN_PUBLISHED = "CTMS_PLAN_PUBLISHED"
    CTMS_ASSIGNMENT_INVALID = "CTMS_ASSIGNMENT_INVALID"
    CTMS_OWNERSHIP_CONFLICT = "CTMS_OWNERSHIP_CONFLICT"
    PROJECTION_FIELD_NOT_ALLOWED = "PROJECTION_FIELD_NOT_ALLOWED"
    COORDINATION_REPLAY = "COORDINATION_REPLAY"
    COORDINATION_RETRYING = "COORDINATION_RETRYING"
    COORDINATION_FAILED_EVENT = "COORDINATION_FAILED_EVENT"
    COORDINATION_CONFLICT = "COORDINATION_CONFLICT"
    COORDINATION_OUT_OF_ORDER = "COORDINATION_OUT_OF_ORDER"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    OWNERSHIP_VIOLATION = "OWNERSHIP_VIOLATION"
    DATA_MINIMIZATION_FAILED = "DATA_MINIMIZATION_FAILED"
    REPORT_SCOPE_DENIED = "REPORT_SCOPE_DENIED"
    CTMS_RATE_LIMITED = "CTMS_RATE_LIMITED"
    CTMS_REQUEST_TOO_LARGE = "CTMS_REQUEST_TOO_LARGE"


class CTMSErrorBody(ErrorBody):
    """Sanitized CTMS error body; details never carry event/source payloads."""

    code: CTMSErrorCode | str
    details: dict[str, Any] = Field(default_factory=dict)


class CTMSErrorEnvelope(ErrorEnvelope):
    """Shared ``error`` envelope used by documented CTMS error responses."""

    error: CTMSErrorBody


class CTMSPaginationContract(BaseSchema):
    """OpenAPI-visible pagination contract for every CTMS collection."""

    items: list[Any]
    page: int = Field(ge=1, description="1-indexed page number")
    page_size: int = Field(ge=1, le=100, description="Items per page, maximum 100")
    total: int = Field(ge=0, description="Total number of matching records")


class CTMSOwnershipContract(BaseSchema):
    """Explicit ownership rule published for client display and validation."""

    authoritative_module: str
    writable_module: str
    projection_target: str | None = None
    projection_types: list[ProjectionType] = Field(default_factory=list)
    rule_status: list[OwnershipRuleStatus] = Field(
        default_factory=lambda: [OwnershipRuleStatus.ACTIVE, OwnershipRuleStatus.RETIRED]
    )


# Aliases make the vocabulary convenient for callers while keeping one schema.
ProjectionState = ProjectionStatus


__all__ = [
    "CTMSErrorBody",
    "CTMSErrorCode",
    "CTMSErrorEnvelope",
    "CTMSOwnershipContract",
    "CTMSPaginationContract",
    "CoordinationConflictCode",
    "CoordinationEventStatus",
    "CoordinationEventType",
    "CoordinationFailureCode",
    "ProjectionState",
]
