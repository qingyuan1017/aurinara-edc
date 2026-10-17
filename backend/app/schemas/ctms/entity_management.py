"""Contracts for CTMS entity configuration and study assignment."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.ctms.entity_management import ManagedEntityType
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema, UtcDatetime


class _EntityAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SiteAttributes(_EntityAttributes):
    country: str | None = Field(default=None, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    fax: str | None = Field(default=None, max_length=50)
    zip_code: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=1000)


class DepotAttributes(_EntityAttributes):
    country: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=50)
    zip_code: str = Field(min_length=1, max_length=30)
    fax: str | None = Field(default=None, max_length=50)
    address: str = Field(min_length=1, max_length=1000)


class StaffAttributes(_EntityAttributes):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)


class ParticipatingOrganizationAttributes(_EntityAttributes):
    address: str = Field(min_length=1, max_length=1000)
    phone: str = Field(min_length=1, max_length=50)
    organization_type: str = Field(min_length=1, max_length=100)
    primary_contact_id: UUID | None = None


class InvestigationalProductAttributes(_EntityAttributes):
    generic_name: str = Field(min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    formulation: str = Field(min_length=1, max_length=255)
    specification: str = Field(min_length=1, max_length=1000)
    pharmaceutical_company_id: UUID


_ATTRIBUTE_SCHEMAS: dict[ManagedEntityType, type[_EntityAttributes]] = {
    ManagedEntityType.SITE: SiteAttributes,
    ManagedEntityType.DEPOT: DepotAttributes,
    ManagedEntityType.STAFF: StaffAttributes,
    ManagedEntityType.PARTICIPATING_ORGANIZATION: ParticipatingOrganizationAttributes,
    ManagedEntityType.INVESTIGATIONAL_PRODUCT: InvestigationalProductAttributes,
}


def validate_managed_entity_attributes(
    entity_type: ManagedEntityType | str,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize the type-specific attributes stored in JSONB."""

    normalized_type = ManagedEntityType(entity_type)
    schema = _ATTRIBUTE_SCHEMAS.get(normalized_type)
    if schema is None:
        return dict(attributes)
    return schema.model_validate(attributes).model_dump(mode="json")


class ManagedEntityCreate(BaseCreateSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    entity_type: ManagedEntityType
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_entity_attributes(self) -> "ManagedEntityCreate":
        self.attributes = validate_managed_entity_attributes(self.entity_type, self.attributes)
        return self


class ManagedSiteCreate(BaseCreateSchema):
    """Reusable CTMS Site master-data input."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    country: str | None = Field(default=None, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    fax: str | None = Field(default=None, max_length=50)
    zip_code: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=1000)


class ManagedEntityUpdate(BaseUpdateSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    attributes: dict[str, Any] | None = None
    active: bool | None = None


class ManagedEntityResponse(BaseSchema):
    id: UUID
    entity_type: ManagedEntityType
    code: str
    name: str
    attributes: dict[str, Any]
    active: bool
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime


class StudyEntityAssignmentCreate(BaseCreateSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    entity_id: UUID
    attributes: dict[str, Any] = Field(default_factory=dict)


class StudySiteAssignmentCreate(BaseCreateSchema):
    """Add an available Site to a Study using that Study's Site identifier."""

    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    site_number: str = Field(min_length=1, max_length=50)


class StudyEntityAssignmentResponse(BaseSchema):
    id: UUID
    study_id: UUID
    entity_id: UUID
    site_id: UUID | None = None
    site_number: str | None = None
    entity: ManagedEntityResponse
    attributes: dict[str, Any]
    created_by: UUID
    correlation_id: UUID
    created_at: UtcDatetime


__all__ = [
    "DepotAttributes",
    "InvestigationalProductAttributes",
    "ManagedEntityCreate",
    "ManagedEntityResponse",
    "ManagedEntityUpdate",
    "ManagedSiteCreate",
    "ParticipatingOrganizationAttributes",
    "SiteAttributes",
    "StaffAttributes",
    "StudyEntityAssignmentCreate",
    "StudyEntityAssignmentResponse",
    "StudySiteAssignmentCreate",
    "validate_managed_entity_attributes",
]
