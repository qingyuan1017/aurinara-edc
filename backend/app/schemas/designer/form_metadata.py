"""Designer-owned CRF form metadata schemas — form/section/field definitions.

These Pydantic contracts were reassigned from the EDC module to the Designer
module as part of the Designer / EDC refactor; they describe design-time form
structure authored in the Designer_Module. The ``Codelist`` schemas remain in
``app.schemas.edc.form_metadata`` (split into the Designer codelist module by a
separate task).

Satisfies Requirements:
  - 4.1: Form definition metadata (name, form code, display order, repeating flag).
  - 4.2: Section and field definitions within a form.
  - 11.1: Ownership reassignment with no stored-value changes.
  - 21.2: List endpoints return a pagination envelope.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    UtcDatetime,
)

# ---------------------------------------------------------------------------
# Enumerations (Requirement 4.2 — supported control types)
# ---------------------------------------------------------------------------


class ControlType(StrEnum):
    """The field control types supported by the form builder (Requirement 4.2)."""

    label = "label"
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
    listbox = "listbox"
    multi_select = "multi-select"
    boolean = "boolean"
    file_upload = "file_upload"
    calculated = "calculated"
    repeating_table = "repeating_table"
    coded_term = "coded_term"
    float = "float"
    slider = "slider"
    body_image = "body_image"
    unit = "unit"


class FormType(StrEnum):
    simple = "simple"
    log = "log"
    grid = "grid"
    header_details = "header_details"


class AccessType(StrEnum):
    open_access = "open_access"
    restricted_edit = "restricted_edit"
    general_blind = "general_blind"


class TextAlign(StrEnum):
    left = "left"
    center = "center"
    right = "right"


class DetailType(StrEnum):
    log = "log"
    grid = "grid"


# ---------------------------------------------------------------------------
# Form definition schemas (Requirement 4.1)
# ---------------------------------------------------------------------------


class FormDefinitionCreate(BaseCreateSchema):
    """Request body for creating a form definition (Requirement 4.1)."""

    name: str = Field(..., min_length=1, max_length=255)
    form_code: str = Field(..., min_length=1, max_length=50, description='e.g. "AE", "CM", "DM"')
    display_order: int = Field(..., description="Sort order within the version")
    is_repeating: bool = Field(False, description="Whether the form is repeating")
    form_type: FormType = FormType.simple
    access_type: AccessType = AccessType.open_access
    domain: str | None = Field(None, max_length=50)
    label: str | None = Field(None, max_length=255)
    grid_rows: int | None = Field(None, ge=1)
    grid_columns: int | None = Field(None, ge=1)
    header_name: str | None = Field(None, min_length=1, max_length=255)
    detail_name: str | None = Field(None, min_length=1, max_length=255)
    detail_type: DetailType | None = None
    show_variable_name: bool = False
    show_crf_id: bool = False
    show_odm_id: bool = False


class FormDefinitionUpdate(BaseUpdateSchema):
    """Request body for editing a form definition (Requirement 4.1)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    form_code: str | None = Field(None, min_length=1, max_length=50)
    display_order: int | None = None
    is_repeating: bool | None = None
    form_type: FormType | None = None
    access_type: AccessType | None = None
    domain: str | None = Field(None, max_length=50)
    label: str | None = Field(None, max_length=255)
    grid_rows: int | None = Field(None, ge=1)
    grid_columns: int | None = Field(None, ge=1)
    header_name: str | None = Field(None, min_length=1, max_length=255)
    detail_name: str | None = Field(None, min_length=1, max_length=255)
    detail_type: DetailType | None = None
    show_variable_name: bool | None = None
    show_crf_id: bool | None = None
    show_odm_id: bool | None = None


class FormDefinitionResponse(BaseSchema):
    """Response schema for a form definition (Requirement 4.1)."""

    id: UUID
    study_version_id: UUID
    name: str
    form_code: str
    display_order: int
    is_repeating: bool
    form_type: str
    access_type: str
    domain: str | None = None
    label: str | None = None
    grid_rows: int | None = None
    grid_columns: int | None = None
    header_name: str | None = None
    detail_name: str | None = None
    detail_type: str | None = None
    show_variable_name: bool
    show_crf_id: bool
    show_odm_id: bool
    created_at: UtcDatetime
    sections: list[FormSectionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Section schemas (Requirement 4.2)
# ---------------------------------------------------------------------------


class FormSectionCreate(BaseCreateSchema):
    """Request body for creating a form section (Requirement 4.2)."""

    name: str = Field(..., min_length=1, max_length=255)
    label: str | None = Field(None, min_length=1, max_length=500)
    display_order: int = Field(..., description="Sort order within the form")
    is_label_only: bool = False
    output_to_dataset: bool = True
    help_text: str | None = None
    access_type: AccessType = AccessType.open_access


class FormSectionUpdate(BaseUpdateSchema):
    """Request body for editing a form section (Requirement 4.2)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    label: str | None = Field(None, min_length=1, max_length=500)
    display_order: int | None = None
    is_label_only: bool | None = None
    output_to_dataset: bool | None = None
    help_text: str | None = None
    access_type: AccessType | None = None


class FormSectionResponse(BaseSchema):
    """Response schema for a form section (Requirement 4.2)."""

    id: UUID
    form_definition_id: UUID
    name: str
    label: str
    display_order: int
    is_label_only: bool
    output_to_dataset: bool
    help_text: str | None = None
    access_type: str
    fields: list[FieldDefinitionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Field definition schemas (Requirement 4.2)
# ---------------------------------------------------------------------------


class FieldDefinitionCreate(BaseCreateSchema):
    """Request body for creating a field definition (Requirement 4.2).

    Supports every control type and field attribute.
    """

    label: str = Field(..., min_length=1, max_length=500)
    question: str | None = None
    caption: str | None = Field(None, max_length=500)
    text_align: TextAlign = TextAlign.left
    variable_name: str = Field(..., min_length=1, max_length=255)
    record_id: str | None = Field(None, max_length=255)
    crf_id: str | None = Field(None, max_length=255)
    odm_id: str | None = Field(None, max_length=255)
    control_type: ControlType
    data_type: str = Field(..., min_length=1, max_length=50)
    display_order: int = Field(..., description="Sort order within the section")
    is_required: bool = False

    # Optional attributes
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
    """Request body for editing a field definition (Requirement 4.2).

    All fields are optional so clients can send partial payloads.
    """

    label: str | None = Field(None, min_length=1, max_length=500)
    question: str | None = None
    caption: str | None = Field(None, max_length=500)
    text_align: TextAlign | None = None
    variable_name: str | None = Field(None, min_length=1, max_length=255)
    record_id: str | None = Field(None, max_length=255)
    crf_id: str | None = Field(None, max_length=255)
    odm_id: str | None = Field(None, max_length=255)
    control_type: ControlType | None = None
    data_type: str | None = Field(None, min_length=1, max_length=50)
    display_order: int | None = None
    is_required: bool | None = None
    form_section_id: UUID | None = Field(
        None, description="Move the field to this section (same form only)."
    )
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
    """Response schema for a field definition (Requirement 4.2)."""

    id: UUID
    form_section_id: UUID
    label: str
    question: str | None = None
    caption: str | None = None
    text_align: str
    variable_name: str
    record_id: str | None = None
    crf_id: str | None = None
    odm_id: str | None = None
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
# Reordering schema (Requirements 4.1, 4.2)
# ---------------------------------------------------------------------------


class ReorderRequest(BaseCreateSchema):
    """Request body for reordering a set of sibling entities by id.

    The ``ordered_ids`` list defines the new display order: the first id
    receives display_order 0, the next 1, and so on.
    """

    ordered_ids: list[UUID] = Field(..., min_length=1)


__all__ = [
    "AccessType",
    "ControlType",
    "DetailType",
    "FieldDefinitionCreate",
    "FieldDefinitionResponse",
    "FieldDefinitionUpdate",
    "FormDefinitionCreate",
    "FormDefinitionResponse",
    "FormDefinitionUpdate",
    "FormSectionCreate",
    "FormSectionResponse",
    "FormSectionUpdate",
    "FormType",
    "ReorderRequest",
    "TextAlign",
]
