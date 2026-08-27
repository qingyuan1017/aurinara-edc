"""Form metadata Pydantic schemas — eCRF form/section/field/codelist definitions.

Satisfies Requirements:
  - 9.1: Form definition metadata (name, form code, display order, repeating flag).
  - 9.2: Section and field definitions within a form.
  - 9.3: Supported field control types.
  - 9.4: Supported field attributes.
  - 9.5: Code lists and code list items referenced by fields.
  - 21.2: List endpoints return a pagination envelope.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema

# ---------------------------------------------------------------------------
# Enumerations (Requirement 9.3 — supported control types)
# ---------------------------------------------------------------------------


class ControlType(StrEnum):
    """The field control types supported by the form builder (Requirement 9.3)."""

    text = "text"
    textarea = "textarea"
    integer = "integer"
    decimal = "decimal"
    date = "date"
    datetime = "datetime"
    time = "time"
    radio = "radio"
    checkbox = "checkbox"
    dropdown = "dropdown"
    multi_select = "multi-select"
    boolean = "boolean"
    file_upload = "file_upload"
    calculated = "calculated"
    repeating_table = "repeating_table"
    coded_term = "coded_term"


# ---------------------------------------------------------------------------
# Form definition schemas (Requirement 9.1)
# ---------------------------------------------------------------------------


class FormDefinitionCreate(BaseCreateSchema):
    """Request body for creating a form definition (Requirement 9.1)."""

    name: str = Field(..., min_length=1, max_length=255)
    form_code: str = Field(
        ..., min_length=1, max_length=50, description='e.g. "AE", "CM", "DM"'
    )
    display_order: int = Field(..., description="Sort order within the version")
    is_repeating: bool = Field(False, description="Whether the form is repeating")


class FormDefinitionUpdate(BaseUpdateSchema):
    """Request body for editing a form definition (Requirement 9.1)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    form_code: str | None = Field(None, min_length=1, max_length=50)
    display_order: int | None = None
    is_repeating: bool | None = None


class FormDefinitionResponse(BaseSchema):
    """Response schema for a form definition (Requirement 9.1)."""

    id: UUID
    study_version_id: UUID
    name: str
    form_code: str
    display_order: int
    is_repeating: bool
    created_at: datetime
    sections: list[FormSectionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Section schemas (Requirement 9.2)
# ---------------------------------------------------------------------------


class FormSectionCreate(BaseCreateSchema):
    """Request body for creating a form section (Requirement 9.2)."""

    name: str = Field(..., min_length=1, max_length=255)
    display_order: int = Field(..., description="Sort order within the form")


class FormSectionUpdate(BaseUpdateSchema):
    """Request body for editing a form section (Requirement 9.2)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    display_order: int | None = None


class FormSectionResponse(BaseSchema):
    """Response schema for a form section (Requirement 9.2)."""

    id: UUID
    form_definition_id: UUID
    name: str
    display_order: int
    fields: list[FieldDefinitionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Field definition schemas (Requirements 9.2, 9.3, 9.4)
# ---------------------------------------------------------------------------


class FieldDefinitionCreate(BaseCreateSchema):
    """Request body for creating a field definition (Requirements 9.2, 9.3, 9.4).

    Supports every control type (Req 9.3) and field attribute (Req 9.4).
    """

    label: str = Field(..., min_length=1, max_length=500)
    variable_name: str = Field(..., min_length=1, max_length=255)
    control_type: ControlType
    data_type: str = Field(..., min_length=1, max_length=50)
    display_order: int = Field(..., description="Sort order within the section")
    is_required: bool = False

    # Optional attributes (Req 9.4)
    codelist_id: UUID | None = None
    default_value: str | None = None
    help_text: str | None = None
    unit: str | None = Field(None, max_length=50)
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    max_length: int | None = Field(None, ge=0)
    decimal_precision: int | None = Field(None, ge=0)
    regex_validation: str | None = None
    visibility_rule: dict | None = None
    is_read_only: bool = False
    is_calculated: bool = False
    calculation_expression: str | None = None


class FieldDefinitionUpdate(BaseUpdateSchema):
    """Request body for editing a field definition (Requirements 9.3, 9.4).

    All fields are optional so clients can send partial payloads.
    """

    label: str | None = Field(None, min_length=1, max_length=500)
    variable_name: str | None = Field(None, min_length=1, max_length=255)
    control_type: ControlType | None = None
    data_type: str | None = Field(None, min_length=1, max_length=50)
    display_order: int | None = None
    is_required: bool | None = None
    codelist_id: UUID | None = None
    default_value: str | None = None
    help_text: str | None = None
    unit: str | None = Field(None, max_length=50)
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    max_length: int | None = Field(None, ge=0)
    decimal_precision: int | None = Field(None, ge=0)
    regex_validation: str | None = None
    visibility_rule: dict | None = None
    is_read_only: bool | None = None
    is_calculated: bool | None = None
    calculation_expression: str | None = None


class FieldDefinitionResponse(BaseSchema):
    """Response schema for a field definition (Requirements 9.2, 9.3, 9.4)."""

    id: UUID
    form_section_id: UUID
    label: str
    variable_name: str
    control_type: str
    data_type: str
    is_required: bool
    codelist_id: UUID | None = None
    default_value: str | None = None
    help_text: str | None = None
    unit: str | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    max_length: int | None = None
    decimal_precision: int | None = None
    regex_validation: str | None = None
    visibility_rule: dict | None = None
    is_read_only: bool
    is_calculated: bool
    calculation_expression: str | None = None
    display_order: int


# ---------------------------------------------------------------------------
# Reordering schema (Requirements 9.1, 9.2)
# ---------------------------------------------------------------------------


class ReorderRequest(BaseCreateSchema):
    """Request body for reordering a set of sibling entities by id.

    The ``ordered_ids`` list defines the new display order: the first id
    receives display_order 0, the next 1, and so on.
    """

    ordered_ids: list[UUID] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Code list schemas (Requirement 9.5)
# ---------------------------------------------------------------------------


class CodelistItemCreate(BaseCreateSchema):
    """Request body for creating a code list item (Requirement 9.5).

    Optional ``normal_low`` / ``normal_high`` carry lab reference-range bounds.
    """

    code: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=500)
    display_order: int = Field(..., description="Sort order within the code list")
    normal_low: Decimal | None = None
    normal_high: Decimal | None = None


class CodelistItemResponse(BaseSchema):
    """Response schema for a code list item (Requirement 9.5)."""

    id: UUID
    codelist_id: UUID
    code: str
    label: str
    display_order: int
    normal_low: Decimal | None = None
    normal_high: Decimal | None = None


class CodelistCreate(BaseCreateSchema):
    """Request body for creating a code list (Requirement 9.5)."""

    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=100)
    items: list[CodelistItemCreate] = Field(
        default_factory=list, description="Optional initial code list items"
    )


class CodelistResponse(BaseSchema):
    """Response schema for a code list (Requirement 9.5)."""

    id: UUID
    study_version_id: UUID
    name: str
    code: str
    items: list[CodelistItemResponse] = Field(default_factory=list)
