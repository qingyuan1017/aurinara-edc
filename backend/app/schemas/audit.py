"""Pydantic v2 schemas for audit trail search, response, and export.

Satisfies Requirements:
  - 18.5: Audit search filterable by user, date, entity, subject, field.
  - 18.6: Audit export of selected events.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import BaseSchema


class AuditSearchFilters(BaseModel):
    """Filters for querying audit events.

    All fields are optional; only provided filters are applied.
    Supports pagination via page/page_size.
    """

    actor_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    study_id: UUID | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None
    field_name: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    request_id: UUID | None = None
    action: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AuditEventResponse(BaseSchema):
    """Response schema for a single audit event."""

    id: UUID
    actor_id: UUID | None = None
    actor_email: str | None = None
    timestamp: datetime
    entity_type: str
    entity_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None
    action: str
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    request_id: UUID
    ip_address: str | None = None
    user_agent: str | None = None


class AuditEventExport(BaseModel):
    """Flat dictionary-friendly schema for audit event export."""

    id: str = Field(description="UUID as string for CSV/export compatibility")
    actor_id: str | None = None
    actor_email: str | None = None
    timestamp: str = Field(description="ISO-8601 UTC timestamp")
    entity_type: str
    entity_id: str
    study_id: str | None = None
    site_id: str | None = None
    subject_id: str | None = None
    action: str
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    request_id: str
    ip_address: str | None = None
    user_agent: str | None = None

    model_config = ConfigDict(from_attributes=True)
