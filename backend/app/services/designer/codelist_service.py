"""Codelist_Service — Designer-owned controlled-vocabulary authoring.

Owns codelist design within a ``Draft_Design`` (``StudyVersion`` in draft).
Codelists are Designer_Definitions reassigned out of the combined EDC form
metadata service into the Designer module.

Enforced design rules (Requirement 6):
  - 6.1: A codelist name is 1-100 characters and unique within the Draft_Design,
         and a codelist carries 1-1000 codelist items; the service persists the
         codelist and its items.
  - 6.2: A duplicate codelist name within the Draft_Design is rejected without
         persisting, and the error identifies the duplicate name.
  - 6.3: Publication of a Design_Version is rejected when a field definition
         references a codelist that does not exist in that version; the error
         identifies the missing codelist reference.
  - 6.4: Each codelist associates with exactly one Design_Version via the
         ``study_versions`` FK.

Mutations are allowed **only while the owning Design_Version is a Draft_Design**
(enforced via ``study_version_service.guard_mutable``). Every mutation writes an
Audit_Event inside the caller's transaction so data and audit commit atomically.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.study_version import StudyVersion
from app.schemas.edc.form_metadata import CodelistCreate, CodelistItemCreate
from app.services.edc.study_version_service import study_version_service

logger = logging.getLogger(__name__)

# Codelist authoring bounds (Requirement 6.1).
NAME_MIN_LENGTH = 1
NAME_MAX_LENGTH = 100
ITEMS_MIN_COUNT = 1
ITEMS_MAX_COUNT = 1000


class CodelistService:
    """Manages codelist design (name, items) for a Design_Version (R6)."""

    # ==================================================================
    # Create (Requirements 6.1, 6.2, 6.4)
    # ==================================================================

    async def create_codelist(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: CodelistCreate,
        actor_id: UUID,
    ) -> Codelist:
        """Create a codelist with its items on a Draft_Design (R6.1, R6.2, R6.4).

        Validates the name length (1-100), name uniqueness within the owning
        Design_Version, and the item count (1-1000) *before* any write; a
        violation raises and persists nothing.

        Args:
            session: Active async session (caller's transaction).
            version: The owning Design_Version (must be a Draft_Design).
            data: Validated :class:`CodelistCreate` payload.
            actor_id: UUID of the acting user.

        Returns:
            The created :class:`Codelist` with its ``items`` eagerly loaded.

        Raises:
            BusinessRuleError: If the owning version is published (R2.4).
            ValidationError: If the name length or item count is out of bounds.
            ConflictError: If the name is not unique within the Draft_Design;
                the error details identify the duplicate name (R6.2).
        """
        # Draft-only guard first — never touch a Published_Design (R2.4).
        study_version_service.guard_mutable(version)

        name = self._validate_name(data.name)
        self._validate_item_count(len(data.items))
        await self._guard_unique_name(session, version.id, name)

        codelist = Codelist(
            study_version_id=version.id,
            name=name,
            code=data.code,
        )
        session.add(codelist)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="codelist",
            entity_id=codelist.id,
            action="create",
            module=Module.DESIGNER,
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"name={codelist.name}, code={codelist.code}",
        )

        for item_data in data.items:
            await self._add_item(session, version, codelist, item_data, actor_id)

        logger.info(
            "Codelist created: id=%s version_id=%s name=%s items=%d actor=%s",
            codelist.id,
            version.id,
            codelist.name,
            len(data.items),
            actor_id,
        )
        return await self._get_with_items(session, codelist.id)

    async def _add_item(
        self,
        session: AsyncSession,
        version: StudyVersion,
        codelist: Codelist,
        data: CodelistItemCreate,
        actor_id: UUID,
    ) -> CodelistItem:
        """Persist a single codelist item and audit it."""
        item = CodelistItem(
            codelist_id=codelist.id,
            code=data.code,
            label=data.label,
            display_order=data.display_order,
            normal_low=data.normal_low,
            normal_high=data.normal_high,
        )
        session.add(item)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="codelist_item",
            entity_id=item.id,
            action="create",
            module=Module.DESIGNER,
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"code={item.code}, label={item.label}",
        )
        return item

    # ==================================================================
    # Validation helpers (Requirements 6.1, 6.2)
    # ==================================================================

    @staticmethod
    def _validate_name(name: str) -> str:
        """Return the trimmed name, enforcing the 1-100 character bound (R6.1)."""
        trimmed = name.strip()
        if not (NAME_MIN_LENGTH <= len(trimmed) <= NAME_MAX_LENGTH):
            raise ValidationError(
                f"Codelist name must be {NAME_MIN_LENGTH} to {NAME_MAX_LENGTH} "
                "characters",
                details={"name_length": len(trimmed)},
            )
        return trimmed

    @staticmethod
    def _validate_item_count(count: int) -> None:
        """Enforce the 1-1000 codelist item bound (R6.1)."""
        if not (ITEMS_MIN_COUNT <= count <= ITEMS_MAX_COUNT):
            raise ValidationError(
                f"A codelist must have {ITEMS_MIN_COUNT} to {ITEMS_MAX_COUNT} "
                "items",
                details={"item_count": count},
            )

    async def _guard_unique_name(
        self, session: AsyncSession, study_version_id: UUID, name: str
    ) -> None:
        """Reject a name already used by a codelist in the same version (R6.2).

        The error identifies the duplicate name so the caller can surface it.
        """
        result = await session.execute(
            select(Codelist.id)
            .where(Codelist.study_version_id == study_version_id)
            .where(func.lower(Codelist.name) == name.lower())
            .limit(1)
        )
        if result.scalars().first() is not None:
            raise ConflictError(
                "A codelist with this name already exists in the draft design",
                details={"duplicate_name": name},
            )

    # ==================================================================
    # Publication validation (Requirement 6.3)
    # ==================================================================

    async def validate_codelist_references(
        self, session: AsyncSession, study_version_id: UUID
    ) -> None:
        """Reject publication when a field references a missing codelist (R6.3).

        A field definition in the Design_Version may carry a ``codelist_id``.
        If that id does not resolve to a codelist belonging to the same
        Design_Version, publication must be rejected and the error must
        identify the missing codelist reference.

        Args:
            session: Active async session.
            study_version_id: The Design_Version being published.

        Raises:
            ValidationError: If any field references a codelist absent from the
                version; details carry the offending field and codelist ids.
        """
        existing_result = await session.execute(
            select(Codelist.id).where(
                Codelist.study_version_id == study_version_id
            )
        )
        existing_codelist_ids = set(existing_result.scalars().all())

        missing: list[dict[str, str]] = []
        for field_id, codelist_id in await self._referenced_codelists(
            session, study_version_id
        ):
            if codelist_id not in existing_codelist_ids:
                missing.append(
                    {
                        "field_definition_id": str(field_id),
                        "missing_codelist_id": str(codelist_id),
                    }
                )

        if missing:
            raise ValidationError(
                "Publication rejected: field definitions reference codelists "
                "that do not exist in this design version",
                details={"missing_codelist_references": missing},
            )

    async def _referenced_codelists(
        self, session: AsyncSession, study_version_id: UUID
    ) -> list[tuple[UUID, UUID]]:
        """Return (field_id, codelist_id) pairs referenced within the version."""
        result = await session.execute(
            select(FieldDefinition.id, FieldDefinition.codelist_id)
            .join(FormSection, FieldDefinition.form_section_id == FormSection.id)
            .join(
                FormDefinition,
                FormSection.form_definition_id == FormDefinition.id,
            )
            .where(FormDefinition.study_version_id == study_version_id)
            .where(FieldDefinition.codelist_id.isnot(None))
        )
        return [(fid, cid) for fid, cid in result.all()]

    # ==================================================================
    # Getters
    # ==================================================================

    async def _get_with_items(
        self, session: AsyncSession, codelist_id: UUID
    ) -> Codelist:
        """Load a codelist with its ``items`` eagerly populated.

        A freshly created codelist has an unloaded ``items`` collection;
        serializing it would emit a lazy load that raises ``MissingGreenlet`` on
        the async engine. Returning a loaded instance keeps serialization
        IO-free.
        """
        result = await session.execute(
            select(Codelist)
            .where(Codelist.id == codelist_id)
            .options(selectinload(Codelist.items))
        )
        return result.scalars().one()

    async def get_codelist(
        self, session: AsyncSession, codelist_id: UUID
    ) -> Codelist:
        """Retrieve a codelist by id, raising ``NotFoundError`` if missing."""
        result = await session.execute(
            select(Codelist).where(Codelist.id == codelist_id)
        )
        codelist = result.scalars().first()
        if codelist is None:
            raise NotFoundError(
                "Codelist not found",
                details={"codelist_id": str(codelist_id)},
            )
        return codelist

    async def list_codelists(
        self, session: AsyncSession, study_version_id: UUID
    ) -> list[Codelist]:
        """List a version's codelists ordered by name."""
        result = await session.execute(
            select(Codelist)
            .where(Codelist.study_version_id == study_version_id)
            .order_by(Codelist.name)
        )
        return list(result.scalars().all())


# Module-level singleton for convenience.
codelist_service = CodelistService()
