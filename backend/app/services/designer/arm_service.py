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
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.schedule_of_assessment import ScheduleOfAssessment
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
        actor_id: UUID | None = None,
    ) -> ArmDefinition:
        """Persist an Arm_Definition within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version.
            name: Arm name; 1-100 characters, unique within the design version.
            display_order: Presentation order; 1-999.
            description: Optional free-text description of the arm.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted ArmDefinition.

        Raises:
            ValidationError: If the name length or display order is out of range.
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

        session.add(arm)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="arm_definition",
            entity_id=arm.id,
            action="create",
            module=Module.DESIGNER,
            new_value=f"name={normalized_name}; display_order={display_order}",
            actor_id=actor_id,
        )

        logger.info(
            "Arm definition created: id=%s design_version_id=%s name=%r",
            arm.id,
            design_version_id,
            normalized_name,
        )
        return arm

    async def get_arm_definition(
        self,
        session: AsyncSession,
        arm_id: UUID,
    ) -> ArmDefinition:
        """Fetch a live arm."""
        result = await session.execute(
            select(ArmDefinition).where(
                ArmDefinition.id == arm_id,
                ArmDefinition.deleted_at.is_(None),
            )
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
        """Partially update an arm's descriptive fields."""
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

        old_values = {key: getattr(arm, key) for key in changes}
        for key, value in changes.items():
            setattr(arm, key, value)

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

    async def list_arm_definitions(
        self,
        session: AsyncSession,
        design_version_id: UUID,
    ) -> list[ArmDefinition]:
        """List a version's Arm_Definitions by display order.

        Reads are not audited (matching the other Designer list reads).

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
            .order_by(ArmDefinition.display_order, ArmDefinition.id)
        )
        return list(result.scalars().all())

    async def delete_arm_definition(
        self,
        session: AsyncSession,
        arm_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> None:
        """Soft-delete a draft arm and its arm-scoped schedule atomically.

        The common schedule and schedules owned by other arms are unchanged.
        The route guards the owning design version as mutable before invoking
        this service, so operational subjects can never reference the arm being
        removed.
        """
        arm = await self.get_arm_definition(session, arm_id)
        schedule_result = await session.execute(
            select(ScheduleOfAssessment)
            .where(
                ScheduleOfAssessment.arm_definition_id == arm.id,
                ScheduleOfAssessment.deleted_at.is_(None),
            )
            .options(selectinload(ScheduleOfAssessment.entries))
        )
        schedules = list(schedule_result.scalars().all())
        now = datetime.now(UTC)
        for schedule in schedules:
            for entry in schedule.entries:
                if entry.deleted_at is None:
                    entry.deleted_at = now
            schedule.deleted_at = now
            schedule.updated_at = now
            await session.flush()
            await audit_service.record(
                session,
                entity_type="schedule_of_assessment",
                entity_id=schedule.id,
                action="delete",
                module=Module.DESIGNER,
                old_value=(
                    f"cascade from arm {arm.id}; "
                    f"design_version_id={arm.study_version_id}"
                ),
                actor_id=actor_id,
            )

        arm.deleted_at = now
        arm.updated_at = now
        await session.flush()
        await audit_service.record(
            session,
            entity_type="arm_definition",
            entity_id=arm.id,
            action="delete",
            module=Module.DESIGNER,
            old_value=f"name={arm.name}; display_order={arm.display_order}",
            actor_id=actor_id,
        )
        logger.info(
            "Arm definition soft-deleted: id=%s cascaded_schedules=%d",
            arm.id,
            len(schedules),
        )


# Module-level singleton for convenience
arm_service = ArmService()
