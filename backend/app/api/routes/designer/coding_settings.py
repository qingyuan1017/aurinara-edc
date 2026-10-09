"""Coding setting authoring routes — Designer-owned.

Handlers for authoring ``Coding_Setting`` records (dictionary reference + rule
per coded item) inside a Draft_Design, delegating to the Designer
``coding_setting_service``.

Satisfies Requirements:
  - 4.8: Persist a coding setting (dictionary reference + rule) per coded item
         within a design version.

Endpoints:
  - POST /versions/{version_id}/coding-settings   create a coding setting
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.coding_setting import (
    CodingSettingCreate,
    CodingSettingResponse,
)
from app.services.designer.coding_setting_service import coding_setting_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-coding-settings"])


@router.post(
    "/{version_id}/coding-settings",
    response_model=CodingSettingResponse,
    status_code=201,
)
async def create_coding_setting(
    version_id: UUID,
    body: CodingSettingCreate,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.coding_setting.configure"))
    ],
) -> CodingSettingResponse:
    """Create a Coding_Setting within a draft Design_Version.

    Permission: study.configure
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    setting = await coding_setting_service.create_coding_setting(
        session,
        design_version_id=version.id,
        dictionary_reference=body.dictionary_reference,
        coding_rule=body.coding_rule,
        field_definition_id=body.field_definition_id,
        actor_id=current_user.id,
    )
    return CodingSettingResponse.model_validate(setting)


__all__ = ["router"]
