"""Arm_Service — authoring of Arm_Definitions.

Owns creation of design-time ``Arm_Definition`` records within a
``Draft_Design``. An arm describes a study arm or treatment group; the service
binds every definition to exactly one ``Design_Version`` and enforces name
uniqueness within that version.

Satisfies Requirements:
  - 4.5: Persist an Arm_Definition within a Draft_Design.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.arm_definition import ArmDefinition
from app.schemas.designer.arm_definition import ArmDefinitionUpdate

logger = logging.getLogger(__name__)

_NAME_MIN_LENGTH = 1
_NAME_MAX_LENGTH = 100
_DISPLAY_ORDER_MIN = 1
_DISPLAY_ORDER_MAX = 999


class ArmService:
    """Creates and validates Arm_Definitions for a Draft_Design."""

    async def create_arm_definition(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        name: str,
        display_order: int,
        description: str | None = None,
        visit_definition_ids: Sequence[UUID] | None = None,
        actor_id: UUID | None = None,
    ) -> ArmDefinition:
        """Persist an Arm_Definition within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version.
            name: Arm name; 1-100 characters, unique within the design version.
            display_order: Presentation order; 1-999.
            description: Optional free-text description of the arm.
            visit_definition_ids: Real visit leaf IDs occurring in this arm
                (standalone or cycle-owned); each must belong to the same
                Design_Version as the arm. Folder/cycle UI selections are
                expanded to their leaf visits before reaching this contract.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted ArmDefinition with its member-visit associations loaded.

        Raises:
            ValidationError: If the name length or display order is out of range,
                a member visit does not exist, or a member visit belongs to a
                different design version.
            ConflictError: If the name already exists within the design version;
                the error details identify the duplicate name.
        """
        normalized_name = name.strip()
        if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
            raise ValidationError(
                "Arm name must be 1 to 100 characters",
                details={"field": "name"},
            )
        if not (_DISPLAY_ORDER_MIN <= display_order <= _DISPLAY_ORDER_MAX):
            raise ValidationError(
                "Arm display order must be between 1 and 999",
                details={"field": "display_order"},
            )

        normalized_description = description.strip() if description is not None else None

        # Uniqueness within the design version. A case-insensitive match treats
        # "Arm A" and "arm a" as the same name within one design version.
        existing = await session.execute(
            select(ArmDefinition.id).where(
                ArmDefinition.study_version_id == design_version_id,
                func.lower(ArmDefinition.name) == normalized_name.lower(),
                ArmDefinition.deleted_at.is_(None),
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "An arm definition with this name already exists in the design version",
                details={
                    "duplicate_name": normalized_name,
                    "design_version_id": str(design_version_id),
                },
            )

        arm = ArmDefinition(
            study_version_id=design_version_id,
            name=normalized_name,
            display_order=display_order,
            description=normalized_description,
        )

        unique_visit_ids, member_visits = await self._resolve_member_visits(
            session,
            design_version_id=design_version_id,
            visit_definition_ids=visit_definition_ids or [],
        )
        arm.visits = member_visits

        session.add(arm)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="arm_definition",
            entity_id=arm.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"name={normalized_name}; display_order={display_order}; "
                f"visit_count={len(unique_visit_ids)}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Arm definition created: id=%s design_version_id=%s name=%r visits=%d",
            arm.id,
            design_version_id,
            normalized_name,
            len(unique_visit_ids),
        )
        return arm

    async def get_arm_definition(
        self,
        session: AsyncSession,
        arm_id: UUID,
    ) -> ArmDefinition:
        """Fetch a live arm and eagerly load its visit membership."""
        result = await session.execute(
            select(ArmDefinition)
            .where(
                ArmDefinition.id == arm_id,
                ArmDefinition.deleted_at.is_(None),
            )
            .options(selectinload(ArmDefinition.visits))
        )
        arm = result.scalars().first()
        if arm is None:
            raise NotFoundError(
                "Arm definition not found",
                details={"arm_id": str(arm_id)},
            )
        return arm

    async def update_arm_definition(
        self,
        session: AsyncSession,
        arm_id: UUID,
        data: ArmDefinitionUpdate,
        *,
        actor_id: UUID | None = None,
    ) -> ArmDefinition:
        """Partially update an arm and replace membership with real visit leaves."""
        arm = await self.get_arm_definition(session, arm_id)
        changes = data.model_dump(exclude_unset=True)

        if "name" in changes:
            normalized_name = str(changes["name"]).strip()
            if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
                raise ValidationError(
                    "Arm name must be 1 to 100 characters",
                    details={"field": "name"},
                )
            if normalized_name.lower() != arm.name.lower():
                existing = await session.execute(
                    select(ArmDefinition.id).where(
                        ArmDefinition.study_version_id == arm.study_version_id,
                        func.lower(ArmDefinition.name) == normalized_name.lower(),
                        ArmDefinition.id != arm.id,
                        ArmDefinition.deleted_at.is_(None),
                    )
                )
                if existing.first() is not None:
                    raise ConflictError(
                        "An arm definition with this name already exists in the design version",
                        details={
                            "duplicate_name": normalized_name,
                            "design_version_id": str(arm.study_version_id),
                        },
                    )
            changes["name"] = normalized_name

        if "display_order" in changes:
            display_order = int(changes["display_order"])
            if not (_DISPLAY_ORDER_MIN <= display_order <= _DISPLAY_ORDER_MAX):
                raise ValidationError(
                    "Arm display order must be between 1 and 999",
                    details={"field": "display_order"},
                )
            changes["display_order"] = display_order

        if "description" in changes and changes["description"] is not None:
            changes["description"] = str(changes["description"]).strip() or None

        old_values = {
            key: (
                [str(visit.id) for visit in arm.visits]
                if key == "visit_definition_ids"
                else getattr(arm, key)
            )
            for key in changes
        }
        visit_ids = changes.pop("visit_definition_ids", None)
        for key, value in changes.items():
            setattr(arm, key, value)

        if visit_ids is not None:
            normalized_ids, member_visits = await self._resolve_member_visits(
                session,
                design_version_id=arm.study_version_id,
                visit_definition_ids=visit_ids,
            )
            arm.visits = member_visits
            changes["visit_definition_ids"] = normalized_ids

        arm.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="arm_definition",
            entity_id=arm.id,
            action="update",
            module=Module.DESIGNER,
            old_value=str(old_values),
            new_value=str(changes),
            actor_id=actor_id,
        )
        logger.info("Arm definition updated: id=%s changes=%s", arm.id, list(changes))
        return await self.get_arm_definition(session, arm.id)

    async def _resolve_member_visits(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        visit_definition_ids: Sequence[UUID],
    ) -> tuple[list[UUID], list[object]]:
        """Validate arm members and return unique IDs plus ORM visit rows."""
        unique_visit_ids = list(dict.fromkeys(visit_definition_ids))
        if not unique_visit_ids:
            return [], []

        visit_model = ArmDefinition.visits.property.mapper.class_
        result = await session.execute(
            select(
                visit_model.id,
                visit_model.study_version_id,
                visit_model.definition_kind,
            ).where(visit_model.id.in_(unique_visit_ids))
        )
        found = {row[0]: (row[1], row[2]) for row in result.all()}
        missing = [visit_id for visit_id in unique_visit_ids if visit_id not in found]
        if missing:
            raise ValidationError(
                "One or more member visit definitions were not found",
                details={"missing_visit_definition_ids": [str(value) for value in missing]},
            )
        cross_version = [
            str(visit_id)
            for visit_id in unique_visit_ids
            if found[visit_id][0] != design_version_id
        ]
        if cross_version:
            raise ValidationError(
                "One or more member visit definitions belong to a different design version",
                details={"cross_version_visit_ids": cross_version},
            )
        container_ids = [
            str(visit_id)
            for visit_id in unique_visit_ids
            if found[visit_id][1] not in {"visit", "cycle_visit"}
        ]
        if container_ids:
            raise ValidationError(
                "Arm membership must contain real visits, not folder or cycle containers",
                details={"container_visit_definition_ids": container_ids},
            )

        visit_result = await session.execute(
            select(visit_model).where(visit_model.id.in_(unique_visit_ids))
        )
        visits_by_id = {visit.id: visit for visit in visit_result.scalars().all()}
        return unique_visit_ids, [visits_by_id[visit_id] for visit_id in unique_visit_ids]

    async def list_arm_definitions(
        self,
        session: AsyncSession,
        design_version_id: UUID,
    ) -> list[ArmDefinition]:
        """List a version's Arm_Definitions (with member visits) by display order.

        Reads are not audited (matching the other Designer list reads). The
        ``visits`` relationship is eager-loaded so the route can serialize the
        member ids without triggering an async lazy load.

        Args:
            session: The active async session.
            design_version_id: The owning Design_Version id.

        Returns:
            The version's ArmDefinitions ordered by ``display_order``.
        """
        result = await session.execute(
            select(ArmDefinition)
            .where(
                ArmDefinition.study_version_id == design_version_id,
                ArmDefinition.deleted_at.is_(None),
            )
            .options(selectinload(ArmDefinition.visits))
            .order_by(ArmDefinition.display_order, ArmDefinition.id)
        )
        return list(result.scalars().all())


# Module-level singleton for convenience
arm_service = ArmService()
