"""Designer-owned visit definition schemas.

These Pydantic contracts describe the design-time authoring of a
Visit_Definition in the Designer_Module. They were reassigned from the EDC
module to the Designer module as part of the Designer / EDC refactor.

Field bounds encode the acceptance criteria of Requirement 4.2 directly:
name is 1-100 characters, visit number is 1-9999, target day is an integer
0-99999, and the lower/upper window bounds are integers 0-99999. The
cross-field rule *lower <= upper* (and its rejection in R4.3) is enforced in the
``visit_definition_service`` so the error can identify the invalid window.

Satisfies Requirements:
  - 4.2: Visit definition metadata and field bounds.
  - 4.3: Field bounds for the window; the ordering rule is service-enforced.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.shared.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema, UtcDatetime

# Shared field bounds (Requirement 4.2).
NAME_MIN_LENGTH = 1
NAME_MAX_LENGTH = 100
VISIT_NUMBER_MIN = 1
VISIT_NUMBER_MAX = 9999
TARGET_DAY_MIN = 0
TARGET_DAY_MAX = 99999
WINDOW_BOUND_MIN = 0
WINDOW_BOUND_MAX = 99999


class VisitDefinitionKind(StrEnum):
    visit = "visit"
    cycle_visit = "cycle_visit"
    folder = "folder"
    cycle = "cycle"


class VisitType(StrEnum):
    scheduled = "scheduled"
    unscheduled = "unscheduled"
    common = "common"
    # Historical values remain valid for existing studies/imports.
    screening = "screening"
    visit = "visit"
    cycle = "cycle"


class VisitCategory(StrEnum):
    screening = "screening"
    pretreatment = "pretreatment"
    treatment = "treatment"
    follow_up = "follow_up"


class VisitSubtype(StrEnum):
    ecoa = "ecoa"
    ediary = "ediary"


class VisitDefinitionCreate(BaseCreateSchema):
    """Request body for defining a study visit (Requirement 4.2).

    Persisted against a draft Design_Version. ``target_day`` and the window
    bounds are optional (e.g. for screening or unscheduled visit types); when
    provided they must fall within the inclusive bounds below. The ordering rule
    (lower window bound ≤ upper window bound) is enforced in the service so the
    rejection error can identify the invalid window (Requirement 4.3).
    """

    name: str = Field(..., min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    definition_kind: VisitDefinitionKind = VisitDefinitionKind.visit
    visit_number: int | None = Field(
        None,
        ge=VISIT_NUMBER_MIN,
        le=VISIT_NUMBER_MAX,
        description="Ordinal number of the visit (1-9999)",
    )
    visit_type: VisitType = VisitType.scheduled
    parent_folder_id: UUID | None = None
    category: VisitCategory | None = None
    subtype: VisitSubtype | None = None
    target_day: int | None = Field(
        None,
        ge=TARGET_DAY_MIN,
        le=TARGET_DAY_MAX,
        description="Day relative to baseline (0-99999; None when not applicable)",
    )
    window_before: int | None = Field(
        None,
        ge=WINDOW_BOUND_MIN,
        le=WINDOW_BOUND_MAX,
        description="Lower window bound: days before target_day (0-99999)",
    )
    window_after: int | None = Field(
        None,
        ge=WINDOW_BOUND_MIN,
        le=WINDOW_BOUND_MAX,
        description="Upper window bound: days after target_day (0-99999)",
    )
    display_order: int = Field(..., description="Sort order within the schedule")
    is_required: bool = Field(True, description="Whether the visit is required")
    repeat_min: int | None = Field(None, ge=0, description="Cycle-only: minimum repeat count")
    repeat_max: int | None = Field(None, ge=0, description="Cycle-only: maximum repeat count")
    cycle_length: int | None = Field(
        None, ge=0, description="Cycle-only: nominal length in days of one iteration"
    )
    member_visit_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_kind(self) -> VisitDefinitionCreate:
        kind = self.definition_kind
        if self.visit_type == VisitType.cycle:
            kind = VisitDefinitionKind.cycle
            self.definition_kind = kind
        if (
            kind in {VisitDefinitionKind.visit, VisitDefinitionKind.cycle_visit}
            and self.visit_number is None
        ):
            raise ValueError("visit_number is required for a visit or cycle visit")
        if kind != VisitDefinitionKind.visit and self.parent_folder_id is not None:
            raise ValueError("Only a visit can have a parent folder")
        if self.member_visit_ids:
            raise ValueError("Cycle visits must be created inside their owning cycle")
        return self


class VisitDefinitionUpdate(BaseUpdateSchema):
    name: str | None = Field(None, min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    visit_number: int | None = Field(None, ge=VISIT_NUMBER_MIN, le=VISIT_NUMBER_MAX)
    visit_type: VisitType | None = None
    parent_folder_id: UUID | None = None
    category: VisitCategory | None = None
    subtype: VisitSubtype | None = None
    target_day: int | None = Field(None, ge=TARGET_DAY_MIN, le=TARGET_DAY_MAX)
    window_before: int | None = Field(None, ge=WINDOW_BOUND_MIN, le=WINDOW_BOUND_MAX)
    window_after: int | None = Field(None, ge=WINDOW_BOUND_MIN, le=WINDOW_BOUND_MAX)
    display_order: int | None = None
    is_required: bool | None = None
    repeat_min: int | None = Field(None, ge=0)
    repeat_max: int | None = Field(None, ge=0)
    cycle_length: int | None = Field(None, ge=0)
    member_visit_ids: list[UUID] | None = Field(
        None,
        deprecated=True,
        description="Read-only membership; create child visits through the owning cycle",
    )


class VisitDefinitionResponse(BaseSchema):
    """Response schema for a visit definition (Requirement 4.2)."""

    id: UUID
    study_version_id: UUID
    name: str
    visit_number: int
    visit_type: str
    definition_kind: str
    parent_folder_id: UUID | None = None
    category: str | None = None
    subtype: str | None = None
    target_day: int | None = None
    window_before: int | None = None
    window_after: int | None = None
    display_order: int
    is_required: bool
    repeat_min: int | None = None
    repeat_max: int | None = None
    cycle_length: int | None = None
    member_visit_ids: list[UUID] = Field(default_factory=list)
    created_at: UtcDatetime


__all__ = [
    "VisitCategory",
    "VisitDefinitionCreate",
    "VisitDefinitionKind",
    "VisitDefinitionResponse",
    "VisitDefinitionUpdate",
    "VisitSubtype",
    "VisitType",
]
