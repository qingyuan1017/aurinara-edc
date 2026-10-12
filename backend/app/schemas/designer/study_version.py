"""Design_Version (Study Version) Pydantic schemas — Designer-owned.

The design-time version schemas were reassigned to the Designer module as part
of the Designer / EDC refactor. They are re-exported from
``app.schemas.edc.study`` for backward compatibility.

Satisfies Requirements:
  - 2.1: Design_Version draft/published lifecycle.
  - 2.2: Publication records actor/timestamp (exposed in the response).
  - 2.9: Amendment creation with reason.
  - 11.1: Ownership reassignment with no stored-value changes.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    UtcDatetime,
)


class StudyVersionCreate(BaseCreateSchema):
    """Schema for creating a new draft Design_Version."""

    version_number: str
    amendment_reason: str | None = None


class StudyAmendmentCreate(BaseCreateSchema):
    """Request body for creating an amendment from a published version."""

    reason: str = Field(..., min_length=1, max_length=10_000)


class StudyVersionResponse(BaseSchema):
    """Response schema for a Design_Version."""

    id: UUID
    study_id: UUID
    version_number: str
    status: str
    amendment_reason: str | None = None
    amended_from_version_id: UUID | None = None
    published_at: UtcDatetime | None = None
    published_by: UUID | None = None
    created_at: UtcDatetime


class DesignValidationCounts(BaseSchema):
    """Definition totals included in the publication-readiness response."""

    forms: int = 0
    sections: int = 0
    fields: int = 0
    visits: int = 0
    scheduled_form_mappings: int = 0
    codelists: int = 0
    codelist_items: int = 0
    edit_checks: int = 0
    subject_phases: int = 0


class DesignValidationIssue(BaseSchema):
    """One sanitized, actionable publication-readiness finding."""

    code: str
    severity: Literal["error", "warning"]
    message: str
    entity_type: str | None = None
    entity_id: UUID | None = None


class DesignValidationResponse(BaseSchema):
    """Aggregate validation result for one Design_Version."""

    version_id: UUID
    valid: bool
    counts: DesignValidationCounts
    issues: list[DesignValidationIssue]


__all__ = [
    "DesignValidationCounts",
    "DesignValidationIssue",
    "DesignValidationResponse",
    "StudyAmendmentCreate",
    "StudyVersionCreate",
    "StudyVersionResponse",
]
