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
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
            visit_definition_ids: Member Visit_Definition IDs occurring in this
                arm (plain visits and cycles); each must belong to the same
                Design_Version as the arm.
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

        # Attach member Visit_Definitions. Resolve the mapped VisitDefinition
        # class off the association relationship so this service never imports
        # the model directly. Enforce (a) every id exists and (b) each belongs to
        # the same design version as the arm — a same-version guard the FK alone
        # cannot express (this is a sensible-default addition, not a port of the
        # retired cycle_service, which performed no version check).
        unique_visit_ids = list(dict.fromkeys(visit_definition_ids or []))
        if unique_visit_ids:
            visit_model = ArmDefinition.visits.property.mapper.class_
            result = await session.execute(
                select(visit_model.id, visit_model.study_version_id).where(
                    visit_model.id.in_(unique_visit_ids)
                )
            )
            rows = result.all()
            found = {row[0]: row[1] for row in rows}
            missing = [vid for vid in unique_visit_ids if vid not in found]
            if missing:
                raise ValidationError(
                    "One or more member visit definitions were not found",
                    details={"missing_visit_definition_ids": [str(v) for v in missing]},
                )
            # compare visit_model.study_version_id (real column) to
            # arm.study_version_id (real column) — neither table has a
            # design_version_id column.
            cross_version = [
                str(vid) for vid in unique_visit_ids if found[vid] != design_version_id
            ]
            if cross_version:
                raise ValidationError(
                    "One or more member visit definitions belong to a different design version",
                    details={"cross_version_visit_ids": cross_version},
                )
            visit_result = await session.execute(
                select(visit_model).where(visit_model.id.in_(unique_visit_ids))
            )
            arm.visits = list(visit_result.scalars().all())

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
