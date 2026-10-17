"""Form metadata schemas — code lists plus backward-compatible re-exports.

The design-time form/section/field schemas were reassigned to the Designer
module and now live in ``app.schemas.designer.form_metadata``. They are
re-exported here so existing import paths (``from app.schemas.edc.form_metadata
import FormDefinitionCreate``) keep working unchanged (R11.1 — additive, no
breakage).

The ``Codelist`` schemas remain defined here; a separate task splits them out
into the Designer codelist module.

Satisfies Requirements:
  - 4.1 / 4.2: form/section/field schemas (now Designer-owned; re-exported).
  - 6.1: Code lists and code list items referenced by fields.
  - 11.1: Ownership reassignment with no stored-value changes.
  - 21.2: List endpoints return a pagination envelope.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import Field

# Form/section/field schemas are owned by the Designer module. Re-exported here
# for backward compatibility with existing ``app.schemas.edc.form_metadata``
# imports.
from app.schemas.designer.form_metadata import (
    ControlType,
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    FieldDefinitionUpdate,
    FormDefinitionCreate,
    FormDefinitionResponse,
    FormDefinitionUpdate,
    FormSectionCreate,
    FormSectionResponse,
    FormSectionUpdate,
    ReorderRequest,
)
from app.schemas.shared.base import (
    BaseCreateSchema,
    BaseSchema,
)

# ---------------------------------------------------------------------------
# Code list schemas (Requirement 6.1)
# ---------------------------------------------------------------------------


class CodelistItemCreate(BaseCreateSchema):
    """Request body for creating a code list item (Requirement 6.1).

    Optional ``normal_low`` / ``normal_high`` carry lab reference-range bounds.
    """

    code: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=500)
    display_order: int = Field(..., description="Sort order within the code list")
    normal_low: Decimal | None = None
    normal_high: Decimal | None = None
    specify: bool = False


class CodelistItemResponse(BaseSchema):
    """Response schema for a code list item (Requirement 6.1)."""

    id: UUID
    codelist_id: UUID
    code: str
    label: str
    display_order: int
    normal_low: Decimal | None = None
    normal_high: Decimal | None = None
    specify: bool = False


class CodelistCreate(BaseCreateSchema):
    """Request body for creating a code list (Requirement 6.1)."""

    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=100)
    items: list[CodelistItemCreate] = Field(
        default_factory=list, description="Optional initial code list items"
    )


class CodelistResponse(BaseSchema):
    """Response schema for a code list (Requirement 6.1)."""

    id: UUID
    study_version_id: UUID
    odm_oid: str | None = None
    name: str
    code: str
    items: list[CodelistItemResponse] = Field(default_factory=list)


# Backward-compatible public surface. Form/section/field schemas are owned by
# ``app.schemas.designer.form_metadata`` and re-exported here.
__all__ = [
    "CodelistCreate",
    "CodelistItemCreate",
    "CodelistItemResponse",
    "CodelistResponse",
    "ControlType",
    "FieldDefinitionCreate",
    "FieldDefinitionResponse",
    "FieldDefinitionUpdate",
    "FormDefinitionCreate",
    "FormDefinitionResponse",
    "FormDefinitionUpdate",
    "FormSectionCreate",
    "FormSectionResponse",
    "FormSectionUpdate",
    "ReorderRequest",
]
