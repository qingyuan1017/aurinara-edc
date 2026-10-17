"""CTMS entity master data and study assignment service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module, utc_now
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.ctms.entity_management import (
    ManagedEntity,
    ManagedEntityType,
    StudyEntityAssignment,
)
from app.models.ctms.reference_data import ReferenceCategory
from app.models.edc.site import Site, SiteStatus
from app.schemas.ctms.entity_management import validate_managed_entity_attributes
from app.services.ctms.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms.ctms_identity_service import CanonicalIdentityResolver
from app.services.ctms.operational_study_service import _actor, _correlation, _correlation_uuid
from app.services.ctms.reference_data_service import resolve_reference_value


def _values(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        return dict(dump(exclude_unset=True))
    raise ValidationError("Entity payload must be an object")


def _validated_attributes(entity_type: str, attributes: Any) -> dict[str, Any]:
    try:
        return validate_managed_entity_attributes(entity_type, dict(attributes or {}))
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(
            "Configured entity attributes are invalid",
            {"field": "attributes", "entity_type": entity_type},
        ) from exc


class EntityManagementService:
    async def create_site_entity(
        self,
        session: AsyncSession,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ManagedEntity:
        """Create reusable Site master data without assigning it to a Study."""

        values = _values(payload)
        name = str(values.pop("name")).strip()
        if not name:
            raise ValidationError("Site name cannot be blank", {"field": "name"})
        attributes = _validated_attributes(ManagedEntityType.SITE.value, values)
        await self._validate_attribute_references(session, ManagedEntityType.SITE.value, attributes)

        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        entity_id = uuid4()
        entity = ManagedEntity(
            id=entity_id,
            entity_type=ManagedEntityType.SITE.value,
            code=str(entity_id).upper(),
            name=name,
            attributes=attributes,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
        )
        session.add(entity)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="managed_entity",
            entity_id=entity.id,
            study_id=None,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["entity_type", "code", "name", "attributes"],
            payload={"managed_entity_type": ManagedEntityType.SITE.value, "code": entity.code},
        )
        return entity

    async def assign_site_to_study(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> StudyEntityAssignment:
        """Assign an available Site master and create a Study-specific Site identity."""

        await CanonicalIdentityResolver(session).resolve_study(study_id)
        values = _values(payload)
        entity_id = UUID(str(values["entity_id"]))
        site_number = str(values["site_number"]).strip()
        if not site_number:
            raise ValidationError("Study Site ID cannot be blank", {"field": "site_number"})
        entity = await session.get(ManagedEntity, entity_id)
        if (
            entity is None
            or entity.deleted_at is not None
            or not entity.active
            or entity.entity_type != ManagedEntityType.SITE.value
        ):
            raise ValidationError(
                "Only an active available Site can be added to a Study",
                {"field": "entity_id", "reason": "SITE_NOT_AVAILABLE"},
            )
        existing = await session.scalar(
            select(StudyEntityAssignment).where(
                StudyEntityAssignment.study_id == study_id,
                StudyEntityAssignment.entity_id == entity_id,
                StudyEntityAssignment.deleted_at.is_(None),
            )
        )
        if existing:
            raise ConflictError(
                "The Site is already assigned to this Study",
                {"reason": "DUPLICATE_RECORD", "entity_id": str(entity_id)},
            )
        duplicate_number = await session.scalar(
            select(Site).where(
                Site.study_id == study_id,
                Site.site_number == site_number,
                Site.deleted_at.is_(None),
            )
        )
        if duplicate_number:
            raise ConflictError(
                "The Study Site ID is already in use",
                {"reason": "DUPLICATE_SITE_NUMBER", "field": "site_number"},
            )

        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        site = Site(
            study_id=study_id,
            site_number=site_number,
            name=entity.name,
            country=entity.attributes.get("country"),
            region=entity.attributes.get("state"),
            address=entity.attributes.get("address"),
            status=SiteStatus.active,
        )
        session.add(site)
        await session.flush()
        assignment = StudyEntityAssignment(
            study_id=study_id,
            entity_id=entity_id,
            site_id=site.id,
            entity=entity,
            site=site,
            attributes={},
            created_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
        )
        session.add(assignment)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="site",
            entity_id=site.id,
            action="create",
            module=Module.CTMS,
            actor_id=actor_uuid,
            correlation_id=correlation,
            study_id=study_id,
            site_id=site.id,
            scope={"study_id": study_id, "site_id": site.id},
            changed_fields=[
                "id",
                "study_id",
                "site_number",
                "name",
                "country",
                "region",
                "address",
            ],
            source_module=Module.CTMS,
            target_module="PLATFORM",
            source_record_id=entity.id,
            target_record_id=site.id,
            new_value=f"site_id={site.id}, site_number={site_number}, entity_id={entity.id}",
        )
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="study_entity_assignment",
            entity_id=assignment.id,
            study_id=study_id,
            site_id=site.id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["study_id", "entity_id", "site_id", "attributes"],
            payload={
                "study_id": study_id,
                "site_id": site.id,
                "site_number": site_number,
                "managed_entity_type": ManagedEntityType.SITE.value,
            },
        )
        return assignment

    async def create_entity(
        self,
        session: AsyncSession,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ManagedEntity:
        values = _values(payload)
        entity_type = str(getattr(values["entity_type"], "value", values["entity_type"]))
        if entity_type == ManagedEntityType.SITE.value:
            raise ValidationError(
                "Sites must be created through the Site directory",
                {"field": "entity_type", "reason": "SITE_DIRECTORY_REQUIRED"},
            )
        attributes = _validated_attributes(entity_type, values.get("attributes"))
        code = str(values["code"]).strip().upper()
        name = str(values["name"]).strip()
        if not code or not name:
            raise ValidationError(
                "Configured entity code and name cannot be blank",
                {"fields": ["code", "name"]},
            )
        await self._validate_attribute_references(session, entity_type, attributes)
        existing = await session.scalar(
            select(ManagedEntity).where(
                ManagedEntity.entity_type == entity_type,
                ManagedEntity.code == code,
                ManagedEntity.deleted_at.is_(None),
            )
        )
        if existing:
            raise ConflictError(
                "A configured entity with this type and code already exists",
                {"reason": "DUPLICATE_RECORD", "entity_type": entity_type, "code": code},
            )
        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        entity = ManagedEntity(
            entity_type=entity_type,
            code=code,
            name=name,
            attributes=attributes,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
        )
        session.add(entity)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="managed_entity",
            entity_id=entity.id,
            study_id=None,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["entity_type", "code", "name", "attributes"],
            payload={"managed_entity_type": entity_type, "code": code},
        )
        return entity

    async def update_entity(
        self,
        session: AsyncSession,
        entity_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ManagedEntity:
        entity = await session.get(ManagedEntity, entity_id)
        if entity is None or entity.deleted_at is not None:
            raise NotFoundError("Configured entity was not found", {"entity_id": str(entity_id)})
        values = _values(payload)
        if (
            entity.entity_type == ManagedEntityType.SITE.value
            and "code" in values
            and values["code"] is not None
            and str(values["code"]).strip().upper() != entity.code
        ):
            raise ValidationError(
                "A Site's generated code cannot be changed",
                {"field": "code", "reason": "CANONICAL_IDENTITY_IMMUTABLE"},
            )
        if "attributes" in values and values["attributes"] is not None:
            values["attributes"] = _validated_attributes(entity.entity_type, values["attributes"])
            await self._validate_attribute_references(
                session, entity.entity_type, values["attributes"]
            )
        changed: list[str] = []
        for field in ("code", "name", "attributes", "active"):
            if field not in values:
                continue
            value = values[field]
            if field == "code" and value is not None:
                value = str(value).strip().upper()
            elif field == "name" and value is not None:
                value = str(value).strip()
            elif field == "attributes" and value is not None:
                value = dict(value)
            if getattr(entity, field) != value:
                setattr(entity, field, value)
                changed.append(field)
        if not entity.code or not entity.name:
            raise ValidationError(
                "Configured entity code and name cannot be blank",
                {"fields": ["code", "name"]},
            )
        if "code" in changed:
            duplicate = await session.scalar(
                select(ManagedEntity).where(
                    ManagedEntity.entity_type == entity.entity_type,
                    ManagedEntity.code == entity.code,
                    ManagedEntity.id != entity.id,
                    ManagedEntity.deleted_at.is_(None),
                )
            )
            if duplicate:
                raise ConflictError(
                    "A configured entity with this type and code already exists",
                    {
                        "reason": "DUPLICATE_RECORD",
                        "entity_type": entity.entity_type,
                        "code": entity.code,
                    },
                )
        if not changed:
            return entity
        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        entity.updated_by = actor_uuid
        entity.updated_at = utc_now()
        canonical_sites: list[Site] = []
        if entity.entity_type == ManagedEntityType.SITE.value:
            assigned_sites = await session.scalars(
                select(Site)
                .join(StudyEntityAssignment, StudyEntityAssignment.site_id == Site.id)
                .where(
                    StudyEntityAssignment.entity_id == entity.id,
                    StudyEntityAssignment.deleted_at.is_(None),
                    Site.deleted_at.is_(None),
                )
            )
            canonical_sites = list(assigned_sites)
            for canonical_site in canonical_sites:
                canonical_site.name = entity.name
                canonical_site.country = entity.attributes.get("country")
                canonical_site.region = entity.attributes.get("state")
                canonical_site.address = entity.attributes.get("address")
                canonical_site.status = SiteStatus.active if entity.active else SiteStatus.inactive
                canonical_site.updated_at = utc_now()
        await session.flush()
        for canonical_site in canonical_sites:
            await audit_service.record(
                session,
                entity_type="site",
                entity_id=canonical_site.id,
                action="update",
                module=Module.CTMS,
                actor_id=actor_uuid,
                correlation_id=correlation,
                study_id=canonical_site.study_id,
                site_id=canonical_site.id,
                scope={"study_id": canonical_site.study_id, "site_id": canonical_site.id},
                changed_fields=changed,
                source_module=Module.CTMS,
                target_module="PLATFORM",
                source_record_id=canonical_site.id,
                target_record_id=canonical_site.id,
                new_value=f"site_id={canonical_site.id}, name={canonical_site.name}",
            )
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="managed_entity",
            entity_id=entity.id,
            study_id=None,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            payload={"managed_entity_type": entity.entity_type, "code": entity.code},
        )
        return entity

    async def _validate_attribute_references(
        self,
        session: AsyncSession,
        entity_type: str,
        attributes: dict[str, Any],
    ) -> None:
        if entity_type in {
            ManagedEntityType.SITE.value,
            ManagedEntityType.DEPOT.value,
            ManagedEntityType.STAFF.value,
        } and attributes.get("country"):
            attributes["country"] = await resolve_reference_value(
                session,
                ReferenceCategory.COUNTRY,
                str(attributes["country"]),
                field="attributes.country",
            )
        if entity_type == ManagedEntityType.PARTICIPATING_ORGANIZATION.value:
            attributes["organization_type"] = await resolve_reference_value(
                session,
                ReferenceCategory.PARTICIPATING_ORGANIZATION_TYPE,
                str(attributes["organization_type"]),
                field="attributes.organization_type",
            )
        reference_id: Any | None = None
        expected_type: ManagedEntityType | None = None
        field: str | None = None
        if entity_type == ManagedEntityType.PARTICIPATING_ORGANIZATION.value:
            reference_id = attributes.get("primary_contact_id")
            expected_type = ManagedEntityType.STAFF
            field = "primary_contact_id"
        elif entity_type == ManagedEntityType.INVESTIGATIONAL_PRODUCT.value:
            reference_id = attributes.get("pharmaceutical_company_id")
            expected_type = ManagedEntityType.PARTICIPATING_ORGANIZATION
            field = "pharmaceutical_company_id"
        if not reference_id or expected_type is None or field is None:
            return
        referenced = await session.get(ManagedEntity, UUID(str(reference_id)))
        if (
            referenced is None
            or referenced.deleted_at is not None
            or not referenced.active
            or referenced.entity_type != expected_type.value
        ):
            raise ValidationError(
                "Configured entity reference is not available",
                {"field": f"attributes.{field}", "expected_entity_type": expected_type.value},
            )

    async def assign_to_study(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> StudyEntityAssignment:
        await CanonicalIdentityResolver(session).resolve_study(study_id)
        values = _values(payload)
        entity_id = UUID(str(values["entity_id"]))
        entity = await session.get(ManagedEntity, entity_id)
        if entity is None or entity.deleted_at is not None or not entity.active:
            raise ValidationError(
                "Only an active configured entity can be added to a study",
                {"field": "entity_id", "reason": "ENTITY_NOT_AVAILABLE"},
            )
        if entity.entity_type == ManagedEntityType.SITE.value:
            raise ValidationError(
                "Sites require a Study Site ID and must use the Site assignment workflow",
                {"field": "entity_id", "reason": "SITE_ASSIGNMENT_REQUIRED"},
            )
        existing = await session.scalar(
            select(StudyEntityAssignment).where(
                StudyEntityAssignment.study_id == study_id,
                StudyEntityAssignment.entity_id == entity_id,
                StudyEntityAssignment.deleted_at.is_(None),
            )
        )
        if existing:
            raise ConflictError(
                "The configured entity is already assigned to this study",
                {"reason": "DUPLICATE_RECORD", "entity_id": str(entity_id)},
            )
        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        assignment = StudyEntityAssignment(
            study_id=study_id,
            entity_id=entity_id,
            entity=entity,
            attributes=dict(values.get("attributes") or {}),
            created_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
        )
        session.add(assignment)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="study_entity_assignment",
            entity_id=assignment.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["study_id", "entity_id", "attributes"],
            payload={"study_id": study_id, "managed_entity_type": entity.entity_type},
        )
        return assignment


entity_management_service = EntityManagementService()

__all__ = ["EntityManagementService", "entity_management_service"]
