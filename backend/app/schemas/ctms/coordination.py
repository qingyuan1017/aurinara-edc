"""Sanitized coordination, failed-event, and conflict API contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.ctms import Module
from app.schemas.base import BaseCreateSchema, BaseSchema


class CoordinationEventResponse(BaseSchema):
    id: UUID
    event_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    source_module: Module | str
    target_module: Module | str = Module.CTMS
    status: str
    correlation_id: str
    source_version: str | None = None
    source_sequence: int | None = None
    current_version: str | None = None
    rule_version: int | None = None
    resulting_projection_id: UUID | None = None
    outcome: str | None = None
    reason: str | None = None
    accepted_at: datetime | None = None
    processed_at: datetime | None = None


class CoordinationEventListResponse(BaseSchema):
    items: list[CoordinationEventResponse]
    page: int
    page_size: int
    total: int


class CoordinationReplayRequest(BaseCreateSchema):
    reason: str = Field(min_length=1, max_length=1000)


class FailedEventResponse(BaseSchema):
    id: UUID
    event_id: UUID
    event_type: str
    source_module: Module | str
    status: str
    reason_code: str
    sanitized_details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    created_at: datetime
    updated_at: datetime | None = None


class ConflictResolveRequest(BaseCreateSchema):
    policy: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)
    selected_value: str | int | float | bool | None = None


class CoordinationConflictResponse(BaseSchema):
    id: UUID
    event_id: UUID | None = None
    entity_type: str
    field_path: str | None = None
    conflict_type: str
    source_version: str | None = None
    current_version: str | None = None
    policy: str | None = None
    status: str
    sanitized_details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    created_at: datetime
    resolved_at: datetime | None = None


class SanitizedListResponse(BaseSchema):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


__all__ = [name for name in globals() if not name.startswith("_")]
