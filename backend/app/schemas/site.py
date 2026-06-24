"""Site Pydantic schemas.

Satisfies Requirements:
  - 6.1: Site metadata — site number, name, PI, country, region, address, status.
  - 6.2: Site number unique within the study (validated at service layer).
  - 6.4: Site deactivation retains the record.
  - 6.5: Site-level user assignment.
  - 21.2: List endpoints return pagination envelope.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.site import SiteStatus
from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema

# ---------------------------------------------------------------------------
# Site schemas (Requirement 6)
# ---------------------------------------------------------------------------


class SiteCreate(BaseCreateSchema):
    """Request body for creating a new Site (Requirement 6.1)."""

    site_number: str = Field(
        ..., min_length=1, max_length=50, description="Unique within the study"
    )
    name: str = Field(..., min_length=1, max_length=255)
    principal_investigator: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    address: str | None = None


class SiteUpdate(BaseUpdateSchema):
    """Request body for updating an existing Site (partial PATCH)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    principal_investigator: str | None = None
    country: str | None = None
    region: str | None = None
    address: str | None = None


class SiteResponse(BaseSchema):
    """Response schema for a Site record (Requirement 6.1)."""

    id: UUID
    study_id: UUID
    site_number: str
    name: str
    principal_investigator: str | None = None
    country: str | None = None
    region: str | None = None
    address: str | None = None
    status: SiteStatus
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Study-Site-User assignment schema (Requirement 6.5)
# ---------------------------------------------------------------------------


class SiteUserAssign(BaseCreateSchema):
    """Request body for assigning a User to a Site within a Study."""

    user_id: UUID


class SiteUserResponse(BaseSchema):
    """Response schema for a StudySiteUser assignment."""

    id: UUID
    study_id: UUID
    site_id: UUID
    user_id: UUID
    assigned_at: datetime
    assigned_by: UUID | None = None
