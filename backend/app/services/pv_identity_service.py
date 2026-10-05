"""Canonical identity resolution for PV_Safety_Module commands.

PV stores read-only references to canonical Study/Site identity and the
EDC-owned ``Subject_Reference``/``Visit_Instance`` identity. It resolves those
references by their stable UUID only, never by a display value, and it never
creates, allocates, or mutates a clinical subject or protocol visit while
resolving one. Unknown, ambiguous, deleted, and cross-scope references fail
before any PV service adds or changes safety state.

This mirrors the CTMS canonical identity resolver so both modules share the
same reference-integrity conventions, but it is PV-owned: resolved references
carry PV as the linking target module and record source/rule/correlation
metadata for traceability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pv import Module
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject
from app.models.visit import VisitInstance


class CanonicalEntityType(StrEnum):
    """Canonical/EDC record types that may be referenced by PV."""

    STUDY = "Study"
    SITE = "Site"
    SUBJECT = "Subject"
    VISIT_INSTANCE = "Visit_Instance"


@dataclass(frozen=True, slots=True)
class IdentityReferenceMetadata:
    """Source/rule/correlation traceability for a canonical reference on a PV record."""

    source_module: Module
    source_identifier: UUID
    target_module: Module
    target_reference: UUID | None
    ownership_rule_version: int
    correlation_id: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for audit/outbox payloads."""

        data = asdict(self)
        data["source_module"] = self.source_module.value
        data["target_module"] = self.target_module.value
        data["source_identifier"] = str(self.source_identifier)
        data["target_reference"] = (
            str(self.target_reference) if self.target_reference is not None else None
        )
        return data


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    """A resolved, read-only canonical/EDC identity referenced by PV."""

    entity_type: CanonicalEntityType
    id: UUID
    source_module: Module = Module.EDC
    ownership_rule_version: int | None = None
    correlation_id: str | None = None

    @property
    def source_identifier(self) -> UUID:
        """The stable identifier PV persists as a read-only canonical reference."""

        return self.id

    def reference_metadata(
        self,
        *,
        target_reference: UUID | None,
        ownership_rule_version: int,
        correlation_id: str,
        target_module: Module = Module.PV,
    ) -> IdentityReferenceMetadata:
        """Build the metadata recorded when this reference is linked to a PV record."""

        return IdentityReferenceMetadata(
            source_module=self.source_module,
            source_identifier=self.id,
            target_module=target_module,
            target_reference=target_reference,
            ownership_rule_version=ownership_rule_version,
            correlation_id=correlation_id,
        )


_ENTITY_MODELS: dict[CanonicalEntityType, type[Any]] = {
    CanonicalEntityType.STUDY: Study,
    CanonicalEntityType.SITE: Site,
    CanonicalEntityType.SUBJECT: Subject,
    CanonicalEntityType.VISIT_INSTANCE: VisitInstance,
}


class PVIdentityResolver:
    """Resolve canonical identities for PV without mutating the session.

    The resolver only reads. It never adds an ORM object, so a PV command that
    references an unknown or ambiguous canonical entity fails before any safety
    state or audit state can change.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve(
        self,
        entity_type: CanonicalEntityType | str,
        identifier: UUID | str,
        *,
        study_id: UUID | str | None = None,
        site_id: UUID | str | None = None,
        subject_id: UUID | str | None = None,
        display_name: str | None = None,
    ) -> CanonicalIdentity:
        """Resolve one canonical record by its stable UUID.

        ``display_name`` is intentionally a separate argument so callers cannot
        accidentally turn a human label into an identity lookup.
        """

        entity = self._entity_type(entity_type)
        canonical_id = self._stable_id(identifier, entity)
        if display_name is not None:
            raise ValidationError(
                message="PV references must use a canonical stable identifier",
                details={"reason": "DISPLAY_NAME_NOT_ALLOWED", "entity_type": entity.value},
            )

        model = _ENTITY_MODELS[entity]
        statement: Select[Any] = select(model).where(model.id == canonical_id)
        deleted_at = getattr(model, "deleted_at", None)
        if deleted_at is not None:
            statement = statement.where(deleted_at.is_(None))

        expected_study = self._optional_id(study_id, "study_id")
        expected_site = self._optional_id(site_id, "site_id")
        expected_subject = self._optional_id(subject_id, "subject_id")
        if entity is not CanonicalEntityType.STUDY and expected_study is not None:
            statement = statement.where(model.study_id == expected_study)
        if entity in {
            CanonicalEntityType.SITE,
            CanonicalEntityType.SUBJECT,
        } and expected_site is not None:
            statement = statement.where(model.site_id == expected_site)
        if entity is CanonicalEntityType.VISIT_INSTANCE and expected_subject is not None:
            statement = statement.where(model.subject_id == expected_subject)

        result = await self.session.execute(statement)
        rows = self._rows(result)
        if not rows:
            raise NotFoundError(
                message=f"Canonical {entity.value} reference was not found",
                details={
                    "reason": "RECORD_NOT_FOUND",
                    "entity_type": entity.value,
                    "source_identifier": str(canonical_id),
                },
            )
        if len(rows) != 1:
            raise ConflictError(
                message=f"Canonical {entity.value} reference is ambiguous",
                details={
                    "reason": "AMBIGUOUS_REFERENCE",
                    "entity_type": entity.value,
                    "source_identifier": str(canonical_id),
                },
            )

        record = rows[0]
        self._validate_scope(
            entity,
            record,
            expected_study=expected_study,
            expected_site=expected_site,
            expected_subject=expected_subject,
        )
        return CanonicalIdentity(entity_type=entity, id=canonical_id)

    async def resolve_study(
        self, identifier: UUID | str, *, display_name: str | None = None
    ) -> CanonicalIdentity:
        return await self.resolve(
            CanonicalEntityType.STUDY, identifier, display_name=display_name
        )

    async def resolve_site(
        self,
        identifier: UUID | str,
        *,
        study_id: UUID | str | None = None,
        display_name: str | None = None,
    ) -> CanonicalIdentity:
        return await self.resolve(
            CanonicalEntityType.SITE,
            identifier,
            study_id=study_id,
            display_name=display_name,
        )

    async def resolve_subject_reference(
        self,
        identifier: UUID | str,
        *,
        study_id: UUID | str | None = None,
        site_id: UUID | str | None = None,
        display_name: str | None = None,
    ) -> CanonicalIdentity:
        """Resolve the EDC ``Subject_Reference`` PV binds a Safety_Case to.

        PV references the EDC clinical subject identity; it does not create,
        allocate, or mutate the EDC clinical subject record.
        """

        return await self.resolve(
            CanonicalEntityType.SUBJECT,
            identifier,
            study_id=study_id,
            site_id=site_id,
            display_name=display_name,
        )

    # Backwards/glossary-friendly alias.
    resolve_subject = resolve_subject_reference

    async def resolve_visit_instance(
        self,
        identifier: UUID | str,
        *,
        subject_id: UUID | str | None = None,
        display_name: str | None = None,
    ) -> CanonicalIdentity:
        return await self.resolve(
            CanonicalEntityType.VISIT_INSTANCE,
            identifier,
            subject_id=subject_id,
            display_name=display_name,
        )

    @staticmethod
    def _entity_type(value: CanonicalEntityType | str) -> CanonicalEntityType:
        try:
            return value if isinstance(value, CanonicalEntityType) else CanonicalEntityType(value)
        except ValueError as exc:
            raise ValidationError(
                message="Unsupported canonical entity type",
                details={"reason": "INVALID_ENTITY_TYPE"},
            ) from exc

    @staticmethod
    def _stable_id(value: UUID | str, entity: CanonicalEntityType) -> UUID:
        if not isinstance(value, (UUID, str)):
            raise ValidationError(
                message="Canonical references must use a stable UUID",
                details={"reason": "STABLE_ID_REQUIRED", "entity_type": entity.value},
            )
        try:
            return value if isinstance(value, UUID) else UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValidationError(
                message="Canonical references must use a stable UUID",
                details={"reason": "DISPLAY_NAME_NOT_ALLOWED", "entity_type": entity.value},
            ) from exc

    @staticmethod
    def _optional_id(value: UUID | str | None, field: str) -> UUID | None:
        if value is None:
            return None
        try:
            return value if isinstance(value, UUID) else UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValidationError(
                message=f"{field} must be a stable UUID",
                details={"reason": "STABLE_ID_REQUIRED", "field": field},
            ) from exc

    @staticmethod
    def _rows(result: Any) -> list[Any]:
        return list(result.scalars().all())

    @staticmethod
    def _validate_scope(
        entity: CanonicalEntityType,
        record: Any,
        *,
        expected_study: UUID | None,
        expected_site: UUID | None,
        expected_subject: UUID | None,
    ) -> None:
        # Query constraints are applied in SQL, but these checks also protect
        # deterministic repositories/fakes that do not implement SQL filters.
        if expected_study is not None and getattr(record, "study_id", None) != expected_study:
            raise ConflictError(
                message=f"Canonical {entity.value} reference is outside the requested study",
                details={"reason": "REFERENCE_SCOPE_MISMATCH", "entity_type": entity.value},
            )
        if expected_site is not None and getattr(record, "site_id", None) != expected_site:
            raise ConflictError(
                message=f"Canonical {entity.value} reference is outside the requested site",
                details={"reason": "REFERENCE_SCOPE_MISMATCH", "entity_type": entity.value},
            )
        if expected_subject is not None and getattr(record, "subject_id", None) != expected_subject:
            raise ConflictError(
                message="Canonical Visit_Instance reference is outside the requested subject",
                details={"reason": "REFERENCE_SCOPE_MISMATCH", "entity_type": entity.value},
            )


# Friendly alias mirroring the CTMS convention.
PVIdentityService = PVIdentityResolver


async def resolve_canonical_identity(
    session: AsyncSession,
    entity_type: CanonicalEntityType | str,
    identifier: UUID | str,
    **scope: UUID | str | None,
) -> CanonicalIdentity:
    """Session-first helper for PV route/service code using shared DI sessions."""

    return await PVIdentityResolver(session).resolve(entity_type, identifier, **scope)


# The lower-case alias is a factory class, matching the existing service module
# convention while keeping session ownership explicit per request/worker.
pv_identity_service = PVIdentityResolver

__all__ = [
    "CanonicalEntityType",
    "CanonicalIdentity",
    "IdentityReferenceMetadata",
    "PVIdentityResolver",
    "PVIdentityService",
    "pv_identity_service",
    "resolve_canonical_identity",
]
