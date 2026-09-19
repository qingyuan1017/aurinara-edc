"""Canonical EDC identity resolution for CTMS commands.

CTMS stores references to EDC-owned records; it does not resolve a study,
site, subject, visit, or query by a display value and it never creates a
clinical record while resolving one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.query import Query
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject
from app.models.visit import VisitInstance


class CanonicalEntityType(StrEnum):
    """EDC record types that may be referenced by CTMS."""

    STUDY = "Study"
    SITE = "Site"
    SUBJECT = "Subject"
    VISIT_INSTANCE = "Visit_Instance"
    QUERY = "Query"


@dataclass(frozen=True, slots=True)
class IdentityLinkMetadata:
    """Traceability metadata for a canonical reference stored by CTMS."""

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
    """A resolved, read-only EDC identity and its traceability context."""

    entity_type: CanonicalEntityType
    id: UUID
    source_module: Module = Module.EDC
    ownership_rule_version: int | None = None
    correlation_id: str | None = None

    @property
    def source_identifier(self) -> UUID:
        """The stable EDC identifier used as the CTMS canonical reference."""

        return self.id

    def link_metadata(
        self,
        *,
        target_reference: UUID | None,
        ownership_rule_version: int,
        correlation_id: str,
        target_module: Module = Module.CTMS,
    ) -> IdentityLinkMetadata:
        """Build the metadata required when the reference is linked to CTMS."""

        return IdentityLinkMetadata(
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
    CanonicalEntityType.QUERY: Query,
}


class CanonicalIdentityResolver:
    """Resolve canonical EDC identities without mutating the session."""

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
        """Resolve one EDC record by its stable UUID.

        ``display_name`` is intentionally a separate argument so callers cannot
        accidentally turn a human label into an identity lookup.  Unknown,
        ambiguous, deleted, and cross-scope references fail before a CTMS
        service can add or change state.
        """

        entity = self._entity_type(entity_type)
        canonical_id = self._stable_id(identifier, entity)
        if display_name is not None:
            raise ValidationError(
                message="CTMS references must use a canonical stable identifier",
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
            CanonicalEntityType.QUERY,
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

    async def resolve_subject(
        self,
        identifier: UUID | str,
        *,
        study_id: UUID | str | None = None,
        site_id: UUID | str | None = None,
        display_name: str | None = None,
    ) -> CanonicalIdentity:
        return await self.resolve(
            CanonicalEntityType.SUBJECT,
            identifier,
            study_id=study_id,
            site_id=site_id,
            display_name=display_name,
        )

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

    async def resolve_query(
        self,
        identifier: UUID | str,
        *,
        study_id: UUID | str | None = None,
        site_id: UUID | str | None = None,
        display_name: str | None = None,
    ) -> CanonicalIdentity:
        return await self.resolve(
            CanonicalEntityType.QUERY,
            identifier,
            study_id=study_id,
            site_id=site_id,
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
        scalar_result = result.scalars()
        rows = scalar_result.all()
        return list(rows)

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


# Friendly alias used by services and tests.
CanonicalIdentityService = CanonicalIdentityResolver


async def resolve_canonical_identity(
    session: AsyncSession,
    entity_type: CanonicalEntityType | str,
    identifier: UUID | str,
    **scope: UUID | str | None,
) -> CanonicalIdentity:
    """Session-first helper for route/service code using shared DI sessions."""

    return await CanonicalIdentityResolver(session).resolve(
        entity_type, identifier, **scope
    )


# The lower-case alias is a factory class, matching the existing service module
# convention while keeping session ownership explicit per request/worker.
ctms_identity_service = CanonicalIdentityResolver

__all__ = [
    "CanonicalEntityType",
    "CanonicalIdentity",
    "CanonicalIdentityResolver",
    "CanonicalIdentityService",
    "IdentityLinkMetadata",
    "resolve_canonical_identity",
]
