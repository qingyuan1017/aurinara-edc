"""Subject_Phase_Service — authoring of Subject_Phase_Definitions.

Owns creation of design-time ``Subject_Phase_Definition`` records within a
``Draft_Design``. The service enforces name uniqueness within a single design
version and binds every definition to exactly one ``Design_Version``.

Satisfies Requirements:
  - 3.1: Persist a Subject_Phase_Definition with a name of 1-100 characters that
         is unique within its design version and a display order of 1-999.
  - 3.2: Reject a non-unique name, persist nothing, and return an error that
         identifies the duplicate name.
  - 3.3: Associate each Subject_Phase_Definition with exactly one Design_Version.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, ValidationError
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition

logger = logging.getLogger(__name__)

_NAME_MIN_LENGTH = 1
_NAME_MAX_LENGTH = 100
_DISPLAY_ORDER_MIN = 1
_DISPLAY_ORDER_MAX = 999


class SubjectPhaseService:
    """Creates and validates Subject_Phase_Definitions for a Draft_Design."""

    async def create_phase_definition(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        name: str,
        display_order: int,
        actor_id: UUID | None = None,
    ) -> SubjectPhaseDefinition:
        """Persist a Subject_Phase_Definition within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R3.3).
            name: Phase name; 1-100 characters, unique within the design version.
            display_order: Presentation order; 1-999.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted SubjectPhaseDefinition.

        Raises:
            ValidationError: If the name length or display order is out of range.
            ConflictError: If the name already exists within the design version;
                the error details identify the duplicate name (R3.2).
        """
        normalized_name = name.strip()
        if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
            raise ValidationError(
                "Subject phase name must be 1 to 100 characters",
                details={"field": "name"},
            )
        if not (_DISPLAY_ORDER_MIN <= display_order <= _DISPLAY_ORDER_MAX):
            raise ValidationError(
                "Subject phase display order must be between 1 and 999",
                details={"field": "display_order"},
            )

        # Uniqueness within the design version (R3.2). A case-insensitive match
        # treats "Screening" and "screening" as the same phase name within one
        # design version.
        existing = await session.execute(
            select(SubjectPhaseDefinition.id).where(
                SubjectPhaseDefinition.design_version_id == design_version_id,
                func.lower(SubjectPhaseDefinition.name) == normalized_name.lower(),
                SubjectPhaseDefinition.deleted_at.is_(None),
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "A subject phase definition with this name already exists in the design version",
                details={
                    "duplicate_name": normalized_name,
                    "design_version_id": str(design_version_id),
                },
            )

        phase = SubjectPhaseDefinition(
            design_version_id=design_version_id,
            name=normalized_name,
            display_order=display_order,
        )
        session.add(phase)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject_phase_definition",
            entity_id=phase.id,
            action="create",
            module=Module.DESIGNER,
            new_value=f"name={normalized_name}; display_order={display_order}",
            actor_id=actor_id,
        )

        logger.info(
            "Subject phase definition created: id=%s design_version_id=%s name=%r",
            phase.id,
            design_version_id,
            normalized_name,
        )
        return phase


# Module-level singleton for convenience
subject_phase_service = SubjectPhaseService()
