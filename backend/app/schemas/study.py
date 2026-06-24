"""Study and Study Version Pydantic schemas.

Satisfies Requirements:
  - 4.1: Study metadata — code, protocol number, title, sponsor, phase,
          therapeutic area, indication, status.
  - 4.2: Globally unique study code (validated at service layer).
  - 4.3: Study status transitions (enforced at service layer).
  - 5.1: Study versions with draft/published lifecycle.
  - 5.2: Immutability of published versions.
  - 5.3: Amendment creation with reason.
  - 21.2: List endpoints return pagination envelope.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.study import StudyStatus
from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema

# ---------------------------------------------------------------------------
# Study schemas (Requirement 4)
# ---------------------------------------------------------------------------


class StudyCreate(BaseCreateSchema):
    """Request body for creating a new Study (Requirement 4.1)."""

    study_code: str = Field(..., min_length=1, max_length=100, description="Globally unique study code")
    protocol_number: str | None = Field(None, max_length=100)
    title: str = Field(..., min_length=1, max_length=500)
    sponsor: str | None = Field(None, max_length=255)
    phase: str | None = Field(None, max_length=50, description="e.g. Phase I, Phase II, Phase III, Phase IV")
    therapeutic_area: str | None = Field(None, max_length=255)
    indication: str | None = Field(None, max_length=255)


class StudyUpdate(BaseUpdateSchema):
    """Request body for updating an existing Study (partial PATCH)."""

    protocol_number: str | None = None
    title: str | None = Field(None, min_length=1, max_length=500)
    sponsor: str | None = None
    phase: str | None = None
    therapeutic_area: str | None = None
    indication: str | None = None


class StudyStatusTransition(BaseCreateSchema):
    """Request body for transitioning a Study's status (Requirement 4.3)."""

    target_status: StudyStatus


class StudyResponse(BaseSchema):
    """Response schema for a Study record (Requirement 4.1)."""

    id: UUID
    study_code: str
    protocol_number: str | None = None
    title: str
    sponsor: str | None = None
    phase: str | None = None
    therapeutic_area: str | None = None
    indication: str | None = None
    status: StudyStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime | None = None
    versions: list[StudyVersionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Study Version schemas (Requirement 5)
# ---------------------------------------------------------------------------


class StudyVersionCreate(BaseCreateSchema):
    """Schema for creating a new draft Study_Version."""

    version_number: str
    amendment_reason: str | None = None


class StudyVersionResponse(BaseSchema):
    """Response schema for a Study_Version."""

    id: UUID
    study_id: UUID
    version_number: str
    status: str
    amendment_reason: str | None = None
    published_at: datetime | None = None
    published_by: UUID | None = None
    created_at: datetime
