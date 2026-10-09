"""Coding_Setting_Service — authoring of Coding_Settings.

Owns creation of design-time ``Coding_Setting`` records within a
``Draft_Design``. Each setting records a coding dictionary reference and an
optional coding rule for a coded item, optionally scoped to a specific field,
and binds to exactly one ``Design_Version``.

Satisfies Requirements:
  - 4.8: Persist a coding setting (dictionary reference + rule) per coded item
         within a design version, bound to exactly one Design_Version, with an
         audit event.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.designer.coding_setting import CodingSetting

logger = logging.getLogger(__name__)

_DICTIONARY_REFERENCE_MIN_LENGTH = 1
_DICTIONARY_REFERENCE_MAX_LENGTH = 255


class CodingSettingService:
    """Creates and validates Coding_Settings for a Draft_Design."""

    async def create_coding_setting(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        dictionary_reference: str,
        coding_rule: str | None = None,
        field_definition_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> CodingSetting:
        """Persist a Coding_Setting within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R4.8).
            dictionary_reference: The coding dictionary reference; 1-255 chars.
            coding_rule: Optional coding rule.
            field_definition_id: Optional field scope for the coded item.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted CodingSetting.

        Raises:
            ValidationError: If the dictionary reference length is out of range.
        """
        normalized_reference = dictionary_reference.strip()
        if not (
            _DICTIONARY_REFERENCE_MIN_LENGTH
            <= len(normalized_reference)
            <= _DICTIONARY_REFERENCE_MAX_LENGTH
        ):
            raise ValidationError(
                "Coding setting dictionary reference must be 1 to 255 characters",
                details={"field": "dictionary_reference"},
            )

        setting = CodingSetting(
            design_version_id=design_version_id,
            dictionary_reference=normalized_reference,
            coding_rule=coding_rule,
            field_definition_id=field_definition_id,
        )
        session.add(setting)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="coding_setting",
            entity_id=setting.id,
            action="create",
            module=Module.DESIGNER,
            new_value=f"dictionary_reference={normalized_reference}",
            actor_id=actor_id,
        )

        logger.info(
            "Coding setting created: id=%s design_version_id=%s dictionary_reference=%r",
            setting.id,
            design_version_id,
            normalized_reference,
        )
        return setting


# Module-level singleton for convenience
coding_setting_service = CodingSettingService()
