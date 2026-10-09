"""Crf_Access_Service — authoring of Crf_Access_Definitions.

Owns creation of design-time ``Crf_Access_Definition`` records within a
``Draft_Design``. Each definition grants a single role read and/or write access
to a form, a field, or (when both are omitted) the whole design, and binds to
exactly one ``Design_Version``.

Satisfies Requirements:
  - 4.6: Persist per-role read/write access for a form or field within a design
         version, bound to exactly one Design_Version, with an audit event.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.designer.crf_access_definition import CrfAccessDefinition

logger = logging.getLogger(__name__)

_ROLE_MIN_LENGTH = 1
_ROLE_MAX_LENGTH = 100


class CrfAccessService:
    """Creates and validates Crf_Access_Definitions for a Draft_Design."""

    async def create_access_definition(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        role: str,
        can_read: bool,
        can_write: bool,
        form_definition_id: UUID | None = None,
        field_definition_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> CrfAccessDefinition:
        """Persist a Crf_Access_Definition within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R4.6).
            role: The role the grant applies to; 1-100 characters.
            can_read: Whether the role may read the scoped form/field.
            can_write: Whether the role may write the scoped form/field.
            form_definition_id: Optional form scope.
            field_definition_id: Optional field scope.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted CrfAccessDefinition.

        Raises:
            ValidationError: If the role length is out of range.
        """
        normalized_role = role.strip()
        if not (_ROLE_MIN_LENGTH <= len(normalized_role) <= _ROLE_MAX_LENGTH):
            raise ValidationError(
                "CRF access role must be 1 to 100 characters",
                details={"field": "role"},
            )

        access = CrfAccessDefinition(
            design_version_id=design_version_id,
            role=normalized_role,
            form_definition_id=form_definition_id,
            field_definition_id=field_definition_id,
            can_read=can_read,
            can_write=can_write,
        )
        session.add(access)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="crf_access_definition",
            entity_id=access.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"role={normalized_role}; can_read={can_read}; can_write={can_write}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "CRF access definition created: id=%s design_version_id=%s role=%r",
            access.id,
            design_version_id,
            normalized_role,
        )
        return access


# Module-level singleton for convenience
crf_access_service = CrfAccessService()
