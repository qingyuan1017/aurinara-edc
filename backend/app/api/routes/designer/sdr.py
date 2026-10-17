"""Designer-owned versioned SDR selection settings."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_permission_service
from app.core.exceptions import NotFoundError
from app.models.edc.study import StudyVersion
from app.models.shared.identity import User
from app.schemas.edc.operations import SDRSettingResponse, SDRSettingUpsert
from app.services.edc.sdr_service import sdr_service
from app.services.shared.permission_service import PermissionService

router = APIRouter(prefix="/versions", tags=["designer-sdr"])


async def _authorized_version(
    session: AsyncSession,
    version_id: UUID,
    user: User,
    permissions: PermissionService,
    permission: str,
) -> StudyVersion:
    version = await session.get(StudyVersion, version_id)
    if version is None:
        raise NotFoundError(message="Design version not found", details={})
    permissions.require(user, permission, study_id=version.study_id)
    return version


@router.get("/{version_id}/sdr-settings", response_model=SDRSettingResponse)
async def get_sdr_settings(
    version_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SDRSettingResponse:
    await _authorized_version(
        session, version_id, current_user, permission_service, "designer.study_version.read"
    )
    return SDRSettingResponse.model_validate(
        await sdr_service.get_setting(session, version_id)
    )


@router.put("/{version_id}/sdr-settings", response_model=SDRSettingResponse)
async def put_sdr_settings(
    version_id: UUID,
    body: SDRSettingUpsert,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SDRSettingResponse:
    await _authorized_version(
        session, version_id, current_user, permission_service, "designer.sdr.configure"
    )
    return SDRSettingResponse.model_validate(
        await sdr_service.upsert_setting(session, version_id, body, current_user.id)
    )


__all__ = ["router"]
