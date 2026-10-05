"""Pydantic v2 contracts for scoped PV safety audit search and export.

The PV audit trail reuses the shared, immutable append-only ``Audit_Service``
primitive and the shared :class:`~app.models.audit.AuditEvent` model
(``module="PV"``). These transport contracts back the authenticated
``/api/v1/pv`` audit search and export routes.

Search supports exact filtering by user, inclusive UTC date range, entity,
Safety_Case, and Regulatory_Report, and returns matching PV safety Audit_Events
ordered by UTC timestamp ascending with ties broken by Audit_Event identifier
ascending (Requirement 11.4). Export produces exactly the authorized selected
events (Requirement 11.5). Audit_Events are immutable: no update/delete contract
is offered (Requirement 11.6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import BaseSchema


class PVAuditSearchFilters(BaseModel):
    """Exact filters for a scoped PV safety audit search.

    All fields are optional; only provided filters are applied. ``date_from``
    and ``date_to`` are inclusive UTC bounds. ``safety_case_id`` and
    ``regulatory_report_id`` match Audit_Events recorded directly against that
    Safety_Case or Regulatory_Report entity (Requirement 11.4).
    """

    model_config = ConfigDict(extra="forbid")

    actor_id: UUID | None = Field(default=None, description="Exact acting user filter")
    entity_type: str | None = Field(
        default=None, max_length=100, description="Exact PV entity-type filter"
    )
    safety_case_id: UUID | None = Field(
        default=None, description="Audit_Events recorded against this Safety_Case"
    )
    regulatory_report_id: UUID | None = Field(
        default=None, description="Audit_Events recorded against this Regulatory_Report"
    )
    study_id: UUID | None = Field(default=None, description="Study scope filter")
    site_id: UUID | None = Field(default=None, description="Site scope filter")
    date_from: datetime | None = Field(
        default=None, description="Inclusive UTC lower bound on timestamp"
    )
    date_to: datetime | None = Field(
        default=None, description="Inclusive UTC upper bound on timestamp"
    )


class PVAuditEventResponse(BaseSchema):
    """One PV safety Audit_Event as returned by the API.

    The shape is limited to sanitized, caller-safe fields: actor, UTC timestamp,
    entity, study/site scope, action, changed fields, old/new value, and the
    Reason_For_Change. No stack trace, internal database error, prohibited
    safety payload, raw coordination payload, or credential is exposed
    (Requirement 16.3).
    """

    id: UUID
    actor_id: UUID | None = None
    actor_email: str | None = None
    timestamp: datetime
    entity_type: str
    entity_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None
    module: str
    action: str
    correlation_id: str | None = None
    changed_fields: list[str] | None = None
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    request_id: UUID


class PVAuditExportRequest(BaseModel):
    """Request body selecting the PV safety Audit_Events to export.

    The same exact filters as search select the authorized events. The export
    produces exactly the authorized selected events in the deterministic search
    order and records the export action (Requirement 11.5).
    """

    model_config = ConfigDict(extra="forbid")

    filters: PVAuditSearchFilters = Field(default_factory=PVAuditSearchFilters)


class PVAuditExportRow(BaseModel):
    """One flat, export-friendly PV safety Audit_Event row."""

    id: str
    actor_id: str | None = None
    actor_email: str | None = None
    timestamp: str = Field(description="ISO-8601 UTC timestamp")
    entity_type: str
    entity_id: str
    study_id: str | None = None
    site_id: str | None = None
    subject_id: str | None = None
    module: str
    action: str
    correlation_id: str | None = None
    changed_fields: list[str] | None = None
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    request_id: str

    model_config = ConfigDict(from_attributes=True)


class PVAuditExportResponse(BaseModel):
    """The materialized PV safety audit export and its recorded metadata."""

    model_config = ConfigDict(extra="forbid")

    export_id: UUID = Field(description="Identifier of the recorded export action")
    total: int = Field(ge=0, description="Number of exported Audit_Events")
    events: list[PVAuditExportRow]


__all__ = [
    "PVAuditEventResponse",
    "PVAuditExportRequest",
    "PVAuditExportResponse",
    "PVAuditExportRow",
    "PVAuditSearchFilters",
]
