"""Freeze, lock, and unlock routes.

The handlers load each target before checking the target's actual study/site
scope, then delegate all state changes to ``LockService``. The service writes
the control row and its Audit_Event in the injected request transaction.

Satisfies Requirements 16.1, 16.2, 16.4, and 21.1.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_permission_service
from app.core.exceptions import NotFoundError
from app.models.form_data import FormInstance
from app.models.identity import User
from app.models.study import Study
from app.models.subject import Subject
from app.schemas.lock import FreezeLockResponse, UnlockRequest
from app.services.data_capture_service import data_capture_service
from app.services.lock_service import lock_service
from app.services.permission_service import PermissionService

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]

router = APIRouter(tags=["locks"])


async def _get_subject(session: AsyncSession, subject_id: UUID) -> Subject:
    subject = await session.get(Subject, subject_id)
    if subject is None:
        raise NotFoundError("Subject not found", details={"subject_id": str(subject_id)})
    return subject


async def _get_study(session: AsyncSession, study_id: UUID) -> Study:
    study = await session.get(Study, study_id)
    if study is None:
        raise NotFoundError("Study not found", details={"study_id": str(study_id)})
    return study


def _require_lock_access(
    current_user: User,
    permission_service: PermissionService,
    *,
    study_id: UUID,
    site_id: UUID | None = None,
) -> None:
    """Enforce lock management at the target object's actual scope."""
    permission_service.require(
        current_user,
        "lock.manage",
        study_id=study_id,
        site_id=site_id,
    )


async def _get_authorized_form(
    session: AsyncSession,
    form_instance_id: UUID,
    current_user: User,
    permission_service: PermissionService,
) -> FormInstance:
    form_instance = await data_capture_service.load(session, form_instance_id)
    subject = form_instance.subject
    _require_lock_access(
        current_user,
        permission_service,
        study_id=subject.study_id,
        site_id=subject.site_id,
    )
    return form_instance


@router.post(
    "/form-instances/{form_instance_id}/freeze",
    response_model=FreezeLockResponse,
)
async def freeze_form_instance(
    form_instance_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    form_instance = await _get_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    control = await lock_service.freeze(session, form_instance, current_user.id)
    return FreezeLockResponse.model_validate(control)


@router.post(
    "/form-instances/{form_instance_id}/unfreeze",
    response_model=FreezeLockResponse,
)
async def unfreeze_form_instance(
    form_instance_id: UUID,
    body: UnlockRequest,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    form_instance = await _get_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    control = await lock_service.unfreeze(
        session, form_instance, body.reason, current_user.id
    )
    return FreezeLockResponse.model_validate(control)


@router.post(
    "/form-instances/{form_instance_id}/lock",
    response_model=FreezeLockResponse,
)
async def lock_form_instance(
    form_instance_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    form_instance = await _get_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    control = await lock_service.lock(session, form_instance, current_user.id)
    return FreezeLockResponse.model_validate(control)


@router.post(
    "/form-instances/{form_instance_id}/unlock",
    response_model=FreezeLockResponse,
)
async def unlock_form_instance(
    form_instance_id: UUID,
    body: UnlockRequest,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    form_instance = await _get_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    control = await lock_service.unlock(
        session, form_instance, body.reason, current_user.id
    )
    return FreezeLockResponse.model_validate(control)


@router.post("/subjects/{subject_id}/freeze", response_model=FreezeLockResponse)
async def freeze_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    subject = await _get_subject(session, subject_id)
    _require_lock_access(
        current_user,
        permission_service,
        study_id=subject.study_id,
        site_id=subject.site_id,
    )
    control = await lock_service.freeze(session, subject, current_user.id)
    return FreezeLockResponse.model_validate(control)


@router.post("/subjects/{subject_id}/lock", response_model=FreezeLockResponse)
async def lock_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    subject = await _get_subject(session, subject_id)
    _require_lock_access(
        current_user,
        permission_service,
        study_id=subject.study_id,
        site_id=subject.site_id,
    )
    control = await lock_service.lock(session, subject, current_user.id)
    return FreezeLockResponse.model_validate(control)


@router.post("/studies/{study_id}/lock", response_model=FreezeLockResponse)
async def lock_study(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> FreezeLockResponse:
    study = await _get_study(session, study_id)
    _require_lock_access(current_user, permission_service, study_id=study.id)
    control = await lock_service.lock(session, study, current_user.id)
    return FreezeLockResponse.model_validate(control)


__all__ = ["router"]
