"""Study Pydantic schemas, with design-time version schemas re-exported.

Study (identity) schemas stay here; the Design_Version schemas were reassigned
to the Designer module (``app.schemas.designer.study_version``) and are
re-exported below so existing imports keep working (R11.1).

Satisfies Requirements:
  - 4.1: Study metadata — code, protocol number, title, sponsor, phase,
          therapeutic area, indication, status.
  - 4.2: Globally unique study code (validated at service layer).
  - 4.3: Study status transitions (enforced at service layer).
  - 11.1: Ownership reassignment with no stored-value changes.
  - 21.2: List endpoints return pagination envelope.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.edc.study import StudyStatus

# Design_Version schemas are owned by the Designer module. Re-exported here for
# backward compatibility and to resolve the ``StudyResponse.versions`` forward
# reference within this module's namespace.
from app.schemas.designer.study_version import (
    StudyAmendmentCreate,
    StudyVersionCreate,
    StudyVersionResponse,
)
from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    UtcDatetime,
)

# ---------------------------------------------------------------------------
# Study schemas (Requirement 4)
# ---------------------------------------------------------------------------


class StudyCreate(BaseCreateSchema):
    """Request body for creating a new Study (Requirement 4.1)."""

    study_code: str = Field(
        ..., min_length=1, max_length=100, description="Globally unique study code"
    )
    protocol_number: str | None = Field(None, max_length=100)
    title: str = Field(..., min_length=1, max_length=500)
    sponsor: str | None = Field(None, max_length=255)
    phase: str | None = Field(
        None, max_length=50, description="e.g. Phase I, Phase II, Phase III, Phase IV"
    )
    therapeutic_area: str | None = Field(None, max_length=255)
    indication: str | None = Field(None, max_length=255)


class StudyUpdate(BaseUpdateSchema):
    """Request body for updating an existing Study (partial PATCH)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    protocol_number: str | None = None


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
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None
    platform_managed: bool = False
    platform_revision: int | None = None
    platform_registry_status: str | None = None
    versions: list[StudyVersionResponse] = Field(default_factory=list)


# Backward-compatible public surface. The Design_Version schemas
# (``StudyVersionCreate``, ``StudyAmendmentCreate``, ``StudyVersionResponse``)
# are owned by ``app.schemas.designer.study_version`` and re-exported above.
__all__ = [
    "StudyAmendmentCreate",
    "StudyCreate",
    "StudyResponse",
    "StudyStatusTransition",
    "StudyUpdate",
    "StudyVersionCreate",
    "StudyVersionResponse",
]
