"""Raw-data variable setting authoring routes — Designer-owned.

Handlers for authoring ``Raw_Data_Variable_Setting`` records (captured variable
name/type/attributes) inside a Draft_Design, delegating to the Designer
``raw_data_variable_service``.

Satisfies Requirements:
  - 4.7: Persist a raw-data variable setting (name, type, attributes) per
         captured item within a design version.

Endpoints:
  - POST /versions/{version_id}/raw-data-variables   create a variable setting
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.raw_data_variable_setting import (
    RawDataVariableSettingCreate,
    RawDataVariableSettingResponse,
)
from app.services.designer.raw_data_variable_service import raw_data_variable_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-raw-data-variables"])


@router.post(
    "/{version_id}/raw-data-variables",
    response_model=RawDataVariableSettingResponse,
    status_code=201,
)
async def create_raw_data_variable(
    version_id: UUID,
    body: RawDataVariableSettingCreate,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.raw_data_variable.configure"))
    ],
) -> RawDataVariableSettingResponse:
    """Create a Raw_Data_Variable_Setting within a draft Design_Version.

    Permission: study.configure
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    setting = await raw_data_variable_service.create_variable_setting(
        session,
        design_version_id=version.id,
        name=body.name,
        data_type=body.data_type,
        attributes=body.attributes,
        label=body.label,
        suffix=body.suffix,
        actor_id=current_user.id,
    )
    return RawDataVariableSettingResponse.model_validate(setting)


__all__ = ["router"]
