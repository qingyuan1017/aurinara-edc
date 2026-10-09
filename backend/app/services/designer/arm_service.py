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
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, ValidationError
from app.models.designer.arm_definition import ArmDefinition

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


# Module-level singleton for convenience
arm_service = ArmService()
