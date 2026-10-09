"""Raw_Data_Variable_Service — authoring of Raw_Data_Variable_Settings.

Owns creation of design-time ``Raw_Data_Variable_Setting`` records within a
``Draft_Design``. Each setting records a captured variable's name, data type,
and a free-form attributes bag, and binds to exactly one ``Design_Version``.

Satisfies Requirements:
  - 4.7: Persist a raw-data variable setting (name, type, attributes) per
         captured item within a design version, bound to exactly one
         Design_Version, with an audit event.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting

logger = logging.getLogger(__name__)

_NAME_MIN_LENGTH = 1
_NAME_MAX_LENGTH = 255
_DATA_TYPE_MIN_LENGTH = 1
_DATA_TYPE_MAX_LENGTH = 50


class RawDataVariableService:
    """Creates and validates Raw_Data_Variable_Settings for a Draft_Design."""

    async def create_variable_setting(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        name: str,
        data_type: str,
        attributes: dict[str, Any] | None = None,
        actor_id: UUID | None = None,
    ) -> RawDataVariableSetting:
        """Persist a Raw_Data_Variable_Setting within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R4.7).
            name: The variable name; 1-255 characters.
            data_type: The variable data type; 1-50 characters.
            attributes: Optional free-form, type-specific metadata.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted RawDataVariableSetting.

        Raises:
            ValidationError: If the name or data type length is out of range.
        """
        normalized_name = name.strip()
        if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
            raise ValidationError(
                "Raw-data variable name must be 1 to 255 characters",
                details={"field": "name"},
            )
        normalized_data_type = data_type.strip()
        if not (
            _DATA_TYPE_MIN_LENGTH
            <= len(normalized_data_type)
            <= _DATA_TYPE_MAX_LENGTH
        ):
            raise ValidationError(
                "Raw-data variable data type must be 1 to 50 characters",
                details={"field": "data_type"},
            )

        setting = RawDataVariableSetting(
            design_version_id=design_version_id,
            name=normalized_name,
            data_type=normalized_data_type,
            attributes=attributes or {},
        )
        session.add(setting)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="raw_data_variable_setting",
            entity_id=setting.id,
            action="create",
            module=Module.DESIGNER,
            new_value=f"name={normalized_name}; data_type={normalized_data_type}",
            actor_id=actor_id,
        )

        logger.info(
            "Raw-data variable setting created: id=%s design_version_id=%s name=%r",
            setting.id,
            design_version_id,
            normalized_name,
        )
        return setting


# Module-level singleton for convenience
raw_data_variable_service = RawDataVariableService()
