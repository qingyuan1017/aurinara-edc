"""Contracts for atomic Designer JSON imports."""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.schemas.designer.form_metadata import (
    FieldDefinitionCreate,
    FormDefinitionCreate,
    FormSectionCreate,
)
from app.schemas.designer.visit import VisitDefinitionCreate
from app.schemas.edc.edit_check import EditCheckCreate
from app.schemas.edc.form_metadata import CodelistCreate
from app.schemas.shared.base import BaseCreateSchema, BaseSchema


class FieldDefinitionImport(FieldDefinitionCreate):
    """A field that may refer to a codelist by portable code instead of UUID."""

    codelist_code: str | None = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_codelist_reference(self) -> FieldDefinitionImport:
        if self.codelist_id is not None and self.codelist_code is not None:
            raise ValueError("Use either codelist_id or codelist_code, not both")
        return self


class FormSectionImport(FormSectionCreate):
    fields: list[FieldDefinitionImport] = Field(default_factory=list, max_length=1000)


class FormDefinitionImport(FormDefinitionCreate):
    sections: list[FormSectionImport] = Field(default_factory=list, max_length=100)


class DesignerBulkImportRequest(BaseCreateSchema):
    """Designer definitions created together in a single transaction."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    forms: list[FormDefinitionImport] = Field(default_factory=list, max_length=250)
    edit_checks: list[EditCheckCreate] = Field(default_factory=list, max_length=1000)
    codelists: list[CodelistCreate] = Field(default_factory=list, max_length=250)
    visits: list[VisitDefinitionCreate] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def require_content(self) -> DesignerBulkImportRequest:
        if not (self.forms or self.edit_checks or self.codelists or self.visits):
            raise ValueError(
                "Import must contain at least one form, edit check, codelist, or visit"
            )
        return self


class DesignerBulkImportResponse(BaseSchema):
    study_id: UUID
    study_version_id: UUID
    forms_created: int
    sections_created: int
    fields_created: int
    edit_checks_created: int
    codelists_created: int
    codelist_items_created: int
    visits_created: int


__all__ = [
    "DesignerBulkImportRequest",
    "DesignerBulkImportResponse",
    "FieldDefinitionImport",
    "FormDefinitionImport",
    "FormSectionImport",
]
