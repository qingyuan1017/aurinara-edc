"""Sanitized, typed, read-only CTMS projection API contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field

from app.core.ctms import Module, OwnershipState
from app.models.ctms.ownership import ProjectionType
from app.models.ctms.projection import ProjectionStatus
from app.schemas.base import BaseSchema


class ProjectionResponse(BaseSchema):
    """Consumer-facing projection metadata and minimized payload."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    projection_type: str
    source_module: Module
    source_record_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None
    visit_instance_id: UUID | None = None
    query_id: UUID | None = None
    source_version: str | None = None
    source_sequence: int | None = None
    source_timestamp: datetime | None = None
    rule_version: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict, validation_alias="payload_json")
    payload_fingerprint: str | None = None
    rejected_fields_fingerprint: str | None = None
    rejection_reason: str | None = None
    status: ProjectionStatus | OwnershipState | str = ProjectionStatus.CURRENT
    projected_at: datetime
    rebuild_generation: UUID | None = None
    correlation_id: str | None = None

    @property
    def read_only(self) -> bool:
        return True


class ProjectionListResponse(BaseSchema):
    items: list[ProjectionResponse]
    page: int
    page_size: int
    total: int


class ProjectionCreate(BaseSchema):
    """Internal typed projection command; source payload is validated by service."""

    model_config = ConfigDict(extra="forbid")

    projection_type: ProjectionType
    source_module: Module
    source_record_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None
    visit_instance_id: UUID | None = None
    query_id: UUID | None = None
    source_version: str = Field(min_length=1, max_length=128)
    source_sequence: int | None = Field(default=None, ge=0)
    source_timestamp: datetime
    rule_version: int = Field(ge=1)
    correlation_id: str = Field(min_length=1, max_length=128)
    projected_at: datetime | None = None
    rebuild_generation: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ProjectionCreate",
    "ProjectionListResponse",
    "ProjectionResponse",
    "ProjectionStatus",
    "ProjectionType",
]
