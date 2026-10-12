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
    RawDataFieldVariableConfigure,
    RawDatasetDefinitionResponse,
    RawDataVariableSettingCreate,
    RawDataVariableSettingResponse,
)
from app.services.designer.raw_data_variable_service import raw_data_variable_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-raw-data-variables"])


@router.get(
    "/{version_id}/raw-data-variables",
    response_model=list[RawDataVariableSettingResponse],
)
async def list_raw_data_variables(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.raw_data_variable.configure"))
    ],
) -> list[RawDataVariableSettingResponse]:
    """List configured raw-data field suffixes for one design version."""
    await study_version_service.get_version(session, version_id)
    settings = await raw_data_variable_service.list_variable_settings(session, version_id)
    return [RawDataVariableSettingResponse.model_validate(setting) for setting in settings]


@router.get(
    "/{version_id}/raw-data-datasets",
    response_model=list[RawDatasetDefinitionResponse],
)
async def list_raw_data_datasets(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.raw_data_variable.configure"))
    ],
) -> list[RawDatasetDefinitionResponse]:
    """Preview the generated variable schema for each form-owned dataset."""
    await study_version_service.get_version(session, version_id)
    return await raw_data_variable_service.build_dataset_definitions(session, version_id)


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


@router.put(
    "/{version_id}/raw-data-variables/fields/{field_definition_id}",
    response_model=RawDataVariableSettingResponse,
)
async def configure_field_raw_data_variables(
    version_id: UUID,
    field_definition_id: UUID,
    body: RawDataFieldVariableConfigure,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.raw_data_variable.configure"))
    ],
) -> RawDataVariableSettingResponse:
    """Configure companion suffixes for one codelist, numeric, or date field."""
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)
    setting = await raw_data_variable_service.configure_field_setting(
        session,
        design_version_id=version.id,
        field_definition_id=field_definition_id,
        suffix=body.suffix,
        year_suffix=body.year_suffix,
        month_suffix=body.month_suffix,
        day_suffix=body.day_suffix,
        actor_id=current_user.id,
    )
    return RawDataVariableSettingResponse.model_validate(setting)


__all__ = ["router"]
