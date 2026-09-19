"""Pydantic contracts and typed projection allowlist definitions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.ctms import Module, ensure_utc
from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType
from app.schemas.base import BaseCreateSchema, BaseSchema


class ProjectionFieldType(StrEnum):
    """Types permitted in a projection allowlist declaration."""

    UUID = "uuid"
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    ENUM = "enum"


class StatusOwnershipRuleCreate(BaseCreateSchema):
    """Validated request for one immutable ownership-rule version."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=100)
    field_path: str = Field(min_length=1, max_length=255)
    authoritative_module: Module
    writable_module: Module
    projection_target: Module | None = None
    projection_type: ProjectionType | None = None
    allowed_transitions: dict[str, list[str]] = Field(default_factory=dict)
    typed_allowlist: dict[str, ProjectionFieldType | str | dict[str, Any]] = Field(
        default_factory=dict
    )
    version: int = Field(ge=1)
    effective_from: datetime
    effective_to: datetime | None = None
    status: OwnershipRuleStatus = OwnershipRuleStatus.ACTIVE

    @field_validator("entity_type", "field_path")
    @classmethod
    def no_blank_names(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ownership rule names must not be blank")
        return value.strip()

    @field_validator("effective_from", "effective_to")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @model_validator(mode="after")
    def effective_interval_is_ordered(self) -> StatusOwnershipRuleCreate:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        if self.projection_target is self.authoritative_module:
            raise ValueError("projection target must differ from its authoritative module")
        if self.writable_module is not self.authoritative_module:
            raise ValueError("writable module must be the authoritative module")
        return self


class StatusOwnershipRuleResponse(BaseSchema):
    """API representation of a persisted ownership-rule version."""

    id: UUID
    entity_type: str
    field_path: str
    authoritative_module: Module
    writable_module: Module
    projection_target: Module | None
    projection_type: ProjectionType | None
    allowed_transitions: dict[str, list[str]]
    typed_allowlist: dict[str, ProjectionFieldType | str | dict[str, Any]] = Field(
        validation_alias="allowlist_json"
    )
    version: int
    effective_from: datetime
    effective_to: datetime | None
    status: OwnershipRuleStatus
    created_by: UUID | None
    updated_by: UUID | None
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None
    retired_by: UUID | None
    retirement_reason: str | None


class ProjectionValidationResult(BaseSchema):
    """Serializable result from validating a minimized projection payload."""

    accepted: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    rejected_fields: tuple[str, ...] = ()
    reason: str | None = None


# The source-key deny list is deliberately conservative. Unknown keys are also
# rejected, so this list protects callers that use a custom allowlist.
PROHIBITED_PROJECTION_TOKENS: frozenset[str] = frozenset(
    {
        "clinical_data",
        "field_values",
        "field_value",
        "form_instances",
        "form_instance",
        "source_documents",
        "source_document",
        "unrestricted_query_messages",
        "query_messages",
        "query_message",
        "credentials",
        "credential",
        "password",
        "secret",
        "raw_event_body",
        "raw_event_payload",
        "event_body",
        "event_payload",
        "clinical_audit_history",
        "audit_history",
        "subject_number",
        "patient_identifier",
        "direct_identifier",
        "identifier",
        "clinical_identifier",
        "patient_id",
        "mrn",
    }
)


__all__ = [
    "PROHIBITED_PROJECTION_TOKENS",
    "OwnershipRuleStatus",
    "ProjectionFieldType",
    "ProjectionType",
    "ProjectionValidationResult",
    "StatusOwnershipRuleCreate",
    "StatusOwnershipRuleResponse",
]
