"""Designer API for governed custom Python functions."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_permission_service
from app.core.exceptions import AuthorizationError, NotFoundError
from app.models.designer.study_version import StudyVersion
from app.models.shared.identity import User
from app.schemas.designer.custom_function import (
    CustomFunctionCreate,
    CustomFunctionExecuteRequest,
    CustomFunctionExecutionResponse,
    CustomFunctionRejectRequest,
    CustomFunctionResponse,
    CustomFunctionVersionCreate,
    CustomFunctionVersionResponse,
)
from app.services.designer.custom_function_service import custom_function_service
from app.services.edc.study_service import study_service
from app.services.shared.permission_service import PermissionService

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]

router = APIRouter(prefix="/studies", tags=["designer-custom-functions"])
version_router = APIRouter(prefix="/custom-function-versions", tags=["designer-custom-functions"])


async def _get_study_version(
    session: AsyncSession, study_id: UUID, study_version_id: UUID
) -> StudyVersion:
    version = await session.scalar(
        select(StudyVersion).where(
            StudyVersion.id == study_version_id,
            StudyVersion.study_id == study_id,
        )
    )
    if version is None:
        raise NotFoundError(
            "Study version not found",
            details={"study_id": str(study_id), "study_version_id": str(study_version_id)},
        )
    return version


def _require(
    user: User, permission_service: PermissionService, permission: str, study_id: UUID
) -> None:
    permission_service.require(user, permission, study_id=study_id)


def _require_any(
    user: User,
    permission_service: PermissionService,
    study_id: UUID,
    permissions: tuple[str, ...],
) -> None:
    for permission in permissions:
        try:
            _require(user, permission_service, permission, study_id)
            return
        except AuthorizationError:
            continue
    raise AuthorizationError(
        "Insufficient permissions",
        details={
            "required_permissions": list(permissions),
            "study_id": str(study_id),
        },
    )


@router.get("/{study_id}/custom-functions", response_model=list[CustomFunctionResponse])
async def list_custom_functions(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    study_version_id: Annotated[UUID, Query()],
) -> list[CustomFunctionResponse]:
    await study_service.get_study(session, study_id)
    _require_any(
        current_user,
        permission_service,
        study_id,
        (
            "designer.custom_function.author",
            "designer.custom_function.approve",
            "designer.custom_function.execute",
        ),
    )
    version = await _get_study_version(session, study_id, study_version_id)
    definitions = await custom_function_service.list_definitions(session, version.id)
    return [CustomFunctionResponse.model_validate(item) for item in definitions]


@router.post("/{study_id}/custom-functions", response_model=CustomFunctionResponse, status_code=201)
async def create_custom_function(
    study_id: UUID,
    body: CustomFunctionCreate,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    study_version_id: Annotated[UUID, Query()],
) -> CustomFunctionResponse:
    await study_service.get_study(session, study_id)
    _require(current_user, permission_service, "designer.custom_function.author", study_id)
    version = await _get_study_version(session, study_id, study_version_id)
    definition = await custom_function_service.create_definition(
        session, version, body, actor_id=current_user.id
    )
    return CustomFunctionResponse.model_validate(definition)


@router.post(
    "/{study_id}/custom-functions/{definition_id}/versions",
    response_model=CustomFunctionVersionResponse,
    status_code=201,
)
async def create_custom_function_version(
    study_id: UUID,
    definition_id: UUID,
    body: CustomFunctionVersionCreate,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    _require(current_user, permission_service, "designer.custom_function.author", study_id)
    definition = await custom_function_service.get_definition(session, definition_id)
    version = await _get_study_version(session, study_id, definition.study_version_id)
    created = await custom_function_service.create_version(
        session, definition, version, body, actor_id=current_user.id
    )
    return CustomFunctionVersionResponse.model_validate(created)


async def _authorized_version(
    session: AsyncSession,
    user: User,
    permission_service: PermissionService,
    version_id: UUID,
    permission: str,
):
    version, definition, study_version = await custom_function_service.get_version(
        session, version_id
    )
    _require(user, permission_service, permission, study_version.study_id)
    return version, definition, study_version


@version_router.get("/{version_id}", response_model=CustomFunctionVersionResponse)
async def review_custom_function_version(
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    """Return source and provenance to an authorized independent reviewer."""
    version, _, study_version = await custom_function_service.get_version(session, version_id)
    _require_any(
        current_user,
        permission_service,
        study_version.study_id,
        (
            "designer.custom_function.author",
            "designer.custom_function.approve",
        ),
    )
    return CustomFunctionVersionResponse.model_validate(version)


@version_router.post("/{version_id}/submit", response_model=CustomFunctionVersionResponse)
async def submit_custom_function(
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.author",
    )
    return CustomFunctionVersionResponse.model_validate(
        await custom_function_service.submit(session, version, study_version, current_user.id)
    )


@version_router.post("/{version_id}/approve", response_model=CustomFunctionVersionResponse)
async def approve_custom_function(
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.approve",
    )
    return CustomFunctionVersionResponse.model_validate(
        await custom_function_service.approve(session, version, study_version, current_user.id)
    )


@version_router.post("/{version_id}/reject", response_model=CustomFunctionVersionResponse)
async def reject_custom_function(
    version_id: UUID,
    body: CustomFunctionRejectRequest,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.approve",
    )
    return CustomFunctionVersionResponse.model_validate(
        await custom_function_service.reject(
            session, version, study_version, current_user.id, body.reason
        )
    )


@version_router.post("/{version_id}/activate", response_model=CustomFunctionVersionResponse)
async def activate_custom_function(
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.approve",
    )
    return CustomFunctionVersionResponse.model_validate(
        await custom_function_service.activate(session, version, study_version, current_user.id)
    )


@version_router.post("/{version_id}/retire", response_model=CustomFunctionVersionResponse)
async def retire_custom_function(
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.approve",
    )
    return CustomFunctionVersionResponse.model_validate(
        await custom_function_service.retire(session, version, study_version, current_user.id)
    )


@version_router.post("/{version_id}/disable", response_model=CustomFunctionVersionResponse)
async def disable_custom_function(
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionVersionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.approve",
    )
    return CustomFunctionVersionResponse.model_validate(
        await custom_function_service.disable(session, version, study_version, current_user.id)
    )


@version_router.post("/{version_id}/execute", response_model=CustomFunctionExecutionResponse)
async def execute_custom_function(
    version_id: UUID,
    body: CustomFunctionExecuteRequest,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> CustomFunctionExecutionResponse:
    version, _, study_version = await _authorized_version(
        session,
        current_user,
        permission_service,
        version_id,
        "designer.custom_function.execute",
    )
    return await custom_function_service.execute(
        session, version, study_version, body, actor_id=current_user.id
    )


__all__ = ["router", "version_router"]
