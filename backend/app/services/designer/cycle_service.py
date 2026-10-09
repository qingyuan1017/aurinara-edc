"""Cycle_Service — authoring of Cycle_Definitions.

Owns creation of design-time ``Cycle_Definition`` records within a
``Draft_Design``. A cycle is a repeating group of visits; the service persists
the cycle and its member ``Visit_Definition`` associations, binding every
definition to exactly one ``Design_Version``.

Satisfies Requirements:
  - 4.4: Persist a Cycle_Definition and its member Visit_Definitions within a
         Draft_Design.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, ValidationError
from app.models.designer.cycle_definition import CycleDefinition

logger = logging.getLogger(__name__)

_NAME_MIN_LENGTH = 1
_NAME_MAX_LENGTH = 100
_DISPLAY_ORDER_MIN = 1
_DISPLAY_ORDER_MAX = 999


class CycleService:
    """Creates and validates Cycle_Definitions for a Draft_Design."""

    async def create_cycle_definition(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        name: str,
        display_order: int,
        visit_definition_ids: Sequence[UUID] | None = None,
        actor_id: UUID | None = None,
    ) -> CycleDefinition:
        """Persist a Cycle_Definition and its member Visit_Definitions.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version.
            name: Cycle name; 1-100 characters, unique within the design version.
            display_order: Presentation order; 1-999.
            visit_definition_ids: Member Visit_Definition IDs for the cycle (R4.4).
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted CycleDefinition with its member-visit associations.

        Raises:
            ValidationError: If the name length or display order is out of range.
            ConflictError: If the name already exists within the design version;
                the error details identify the duplicate name.
        """
        normalized_name = name.strip()
        if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
            raise ValidationError(
                "Cycle name must be 1 to 100 characters",
                details={"field": "name"},
            )
        if not (_DISPLAY_ORDER_MIN <= display_order <= _DISPLAY_ORDER_MAX):
            raise ValidationError(
                "Cycle display order must be between 1 and 999",
                details={"field": "display_order"},
            )

        # Uniqueness within the design version. A case-insensitive match treats
        # "Cycle 1" and "cycle 1" as the same name within one design version.
        existing = await session.execute(
            select(CycleDefinition.id).where(
                CycleDefinition.study_version_id == design_version_id,
                func.lower(CycleDefinition.name) == normalized_name.lower(),
                CycleDefinition.deleted_at.is_(None),
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "A cycle definition with this name already exists in the design version",
                details={
                    "duplicate_name": normalized_name,
                    "design_version_id": str(design_version_id),
                },
            )

        cycle = CycleDefinition(
            study_version_id=design_version_id,
            name=normalized_name,
            display_order=display_order,
        )

        # Attach member Visit_Definitions (R4.4). Resolve via the ORM registry by
        # loading the mapped VisitDefinition class off the association relationship
        # so this service never imports the model directly.
        unique_visit_ids = list(dict.fromkeys(visit_definition_ids or []))
        if unique_visit_ids:
            visit_model = CycleDefinition.visits.property.mapper.class_
            result = await session.execute(
                select(visit_model).where(visit_model.id.in_(unique_visit_ids))
            )
            visits = list(result.scalars().all())
            found_ids = {visit.id for visit in visits}
            missing = [vid for vid in unique_visit_ids if vid not in found_ids]
            if missing:
                raise ValidationError(
                    "One or more member visit definitions were not found",
                    details={"missing_visit_definition_ids": [str(v) for v in missing]},
                )
            cycle.visits = visits

        session.add(cycle)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="cycle_definition",
            entity_id=cycle.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"name={normalized_name}; display_order={display_order}; "
                f"visit_count={len(unique_visit_ids)}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Cycle definition created: id=%s design_version_id=%s name=%r visits=%d",
            cycle.id,
            design_version_id,
            normalized_name,
            len(unique_visit_ids),
        )
        return cycle


# Module-level singleton for convenience
cycle_service = CycleService()
