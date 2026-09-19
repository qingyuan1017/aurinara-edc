"""Source-data-verification API routes.

Routes load the target hierarchy before authorizing so study/site-scoped
permissions are enforced server-side for polymorphic field and form targets.
The SDV service performs the mutation and audit write in the caller's session;
``get_db`` commits or rolls back that transaction at request completion.

Satisfies Requirements 14.1, 14.2, 14.3, 14.4, and 21.1.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db, get_permission_service
from app.core.exceptions import NotFoundError
from app.models.form_data import FieldValue, FormInstance
from app.models.identity import User
from app.models.sdv import SDVScopeType
from app.models.study import Study
from app.schemas.sdv import SDVProgressResponse, SDVStatusResponse
from app.services.permission_service import PermissionService
from app.services.sdv_service import sdv_service

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]

router = APIRouter(tags=["sdv"])


async def _get_field_value(session: AsyncSession, field_id: UUID) -> FieldValue:
    """Load a field value and its subject hierarchy for authorization/audit."""
    result = await session.execute(
        select(FieldValue)
        .where(FieldValue.id == field_id)
        .options(selectinload(FieldValue.form_instance).selectinload(FormInstance.subject))
    )
    field_value = result.scalars().first()
    if field_value is None:
        raise NotFoundError(
            "Field value not found", details={"field_id": str(field_id)}
        )
    return field_value


async def _get_form_instance(
    session: AsyncSession, form_instance_id: UUID
) -> FormInstance:
    """Load a form instance and its subject hierarchy for authorization/audit."""
    result = await session.execute(
        select(FormInstance)
        .where(FormInstance.id == form_instance_id)
        .options(selectinload(FormInstance.subject))
    )
    form_instance = result.scalars().first()
    if form_instance is None:
        raise NotFoundError(
            "Form instance not found",
            details={"form_instance_id": str(form_instance_id)},
        )
    return form_instance


def _require_target_access(
    current_user: User,
    target: FieldValue | FormInstance,
    permission_service: PermissionService,
) -> None:
    """Require SDV management permission for the target's study/site."""
    subject = target.form_instance.subject if isinstance(target, FieldValue) else target.subject
    permission_service.require(
        current_user,
        "sdv.manage",
        study_id=subject.study_id,
        site_id=subject.site_id,
    )


@router.post(
    "/fields/{field_id}/sdv",
    response_model=SDVStatusResponse,
)
async def set_field_sdv(
    field_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> SDVStatusResponse:
    """Mark a normalized field value as source-data verified."""
    field_value = await _get_field_value(session, field_id)
    _require_target_access(current_user, field_value, permission_service)
    status = await sdv_service.set_sdv(
        session, SDVScopeType.field, field_value, actor_id=current_user
    )
    return SDVStatusResponse.model_validate(status)


@router.post(
    "/fields/{field_id}/unsdv",
    response_model=SDVStatusResponse,
)
async def clear_field_sdv(
    field_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> SDVStatusResponse:
    """Clear source-data verification for a normalized field value."""
    field_value = await _get_field_value(session, field_id)
    _require_target_access(current_user, field_value, permission_service)
    status = await sdv_service.clear_sdv(
        session, SDVScopeType.field, field_value, actor_id=current_user
    )
    return SDVStatusResponse.model_validate(status)


@router.post(
    "/form-instances/{form_instance_id}/sdv",
    response_model=SDVStatusResponse,
)
async def set_form_instance_sdv(
    form_instance_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> SDVStatusResponse:
    """Mark a form instance as source-data verified."""
    form_instance = await _get_form_instance(session, form_instance_id)
    _require_target_access(current_user, form_instance, permission_service)
    status = await sdv_service.set_sdv(
        session, SDVScopeType.form, form_instance, actor_id=current_user
    )
    return SDVStatusResponse.model_validate(status)


@router.post(
    "/form-instances/{form_instance_id}/unsdv",
    response_model=SDVStatusResponse,
)
async def clear_form_instance_sdv(
    form_instance_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> SDVStatusResponse:
    """Clear source-data verification for a form instance."""
    form_instance = await _get_form_instance(session, form_instance_id)
    _require_target_access(current_user, form_instance, permission_service)
    status = await sdv_service.clear_sdv(
        session, SDVScopeType.form, form_instance, actor_id=current_user
    )
    return SDVStatusResponse.model_validate(status)


@router.get(
    "/studies/{study_id}/sdv-progress",
    response_model=SDVProgressResponse,
)
async def get_study_sdv_progress(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> SDVProgressResponse:
    """Return verified and not-verified SDV counts for a study."""
    permission_service.require(current_user, "sdv.manage", study_id=study_id)

    study = await session.get(Study, study_id)
    if study is None:
        raise NotFoundError("Study not found", details={"study_id": str(study_id)})

    counts = await sdv_service.progress(session, study_id=study.id)
    return SDVProgressResponse.model_validate(counts)


__all__ = ["router"]
