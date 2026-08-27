"""Pydantic v2 schemas for form data capture endpoints.

Satisfies Requirements:
  - 10.1: Save draft field values.
  - 10.3: Submit form instance.
  - 10.5: Post-submission field change with Reason_For_Change.
  - 21.1: API request/response schemas.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import BaseSchema

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FieldValueResponse(BaseSchema):
    """Response schema for a single field value within a form instance."""

    id: UUID
    field_definition_id: UUID
    value: str | None = None
    is_not_applicable: bool = False
    created_at: datetime
    updated_at: datetime | None = None
    updated_by: UUID | None = None


class FormInstanceResponse(BaseSchema):
    """Response schema for a form instance with its field values."""

    id: UUID
    subject_id: UUID
    visit_instance_id: UUID | None = None
    form_definition_id: UUID
    status: str
    data_jsonb: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None
    submitted_at: datetime | None = None
    submitted_by: UUID | None = None
    field_values: list[FieldValueResponse] = Field(default_factory=list)
    # Presentation fields for clients rendering a data-entry form. These are
    # assembled from the related form definition by the route layer.
    form_name: str | None = None
    subject_number: str | None = None
    visit_name: str | None = None
    sections: list[dict[str, object]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    is_frozen: bool = False
    is_locked: bool = False


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class FormDataPatch(BaseModel):
    """Request body for saving draft field data.

    Body is a dict mapping field_definition_id (string UUID) to value.
    """

    values: dict[str, Any] = Field(
        ...,
        description="Mapping of field_definition_id (UUID string) to value",
    )

    model_config = ConfigDict(from_attributes=True)


class ChangeValueRequest(BaseModel):
    """Request body for post-submission field change with reason.

    Requirement 10.5: Post-submission changes require a Reason_For_Change.
    """

    field_id: UUID = Field(..., description="The field_definition_id to change")
    value: Any = Field(..., description="The new value for the field")
    reason: str | None = Field(
        default=None,
        description="Reason_For_Change (required for post-submission edits)",
    )

    model_config = ConfigDict(from_attributes=True)
