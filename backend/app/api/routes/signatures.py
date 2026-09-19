"""Electronic signature routes.

The routes load each target before checking its actual study/site scope, then
hand the authenticated identity and re-authentication password to
``SignatureService``.  The service owns the signature and audit writes in the
request transaction.

Endpoints:
  - POST /form-instances/{form_instance_id}/sign
  - POST /subjects/{subject_id}/sign
  - GET  /subjects/{subject_id}/signatures
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_user, get_db, get_permission_service
from app.core.exceptions import NotFoundError
from app.models.form_data import FormInstance
from app.models.identity import User
from app.models.signature import Signature
from app.models.subject import Subject
from app.schemas.base import PaginatedResponse
from app.schemas.signature import SignatureRequest, SignatureResponse
from app.services.data_capture_service import data_capture_service
from app.services.permission_service import PermissionService
from app.services.signature_service import signature_service

DbSession = Annotated[AsyncSession, Depends(get_db)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]

router = APIRouter(tags=["signatures"])


async def _get_subject(session: AsyncSession, subject_id: UUID) -> Subject:
    subject = await session.get(Subject, subject_id)
    if subject is None:
        raise NotFoundError("Subject not found", details={"subject_id": str(subject_id)})
    return subject


async def _get_authorized_form(
    session: AsyncSession,
    form_instance_id: UUID,
    current_user: User,
    permission_service: PermissionService,
) -> FormInstance:
    form_instance = await data_capture_service.load(session, form_instance_id)
    subject = form_instance.subject
    permission_service.require(
        current_user,
        "signature.sign",
        study_id=subject.study_id,
        site_id=subject.site_id,
    )
    return form_instance


def _require_subject_access(
    current_user: User,
    permission_service: PermissionService,
    subject: Subject,
    permission: str,
) -> None:
    permission_service.require(
        current_user,
        permission,
        study_id=subject.study_id,
        site_id=subject.site_id,
    )


@router.post(
    "/form-instances/{form_instance_id}/sign",
    response_model=SignatureResponse,
    status_code=201,
)
async def sign_form_instance(
    form_instance_id: UUID,
    body: SignatureRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: PermissionSvc,
) -> SignatureResponse:
    """Record an investigator signature after password re-authentication."""
    form_instance = await _get_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    signature = await signature_service.sign(
        session,
        form_instance,
        body.meaning,
        credentials=body.password,
        actor_id=current_user,
    )
    return SignatureResponse.model_validate(signature)


@router.post(
    "/subjects/{subject_id}/sign",
    response_model=SignatureResponse,
    status_code=201,
)
async def sign_subject(
    subject_id: UUID,
    body: SignatureRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: PermissionSvc,
) -> SignatureResponse:
    """Record a subject-level attestation after password re-authentication."""
    subject = await _get_subject(session, subject_id)
    _require_subject_access(current_user, permission_service, subject, "signature.sign")
    signature = await signature_service.sign(
        session,
        subject,
        body.meaning,
        credentials=body.password,
        actor_id=current_user,
    )
    return SignatureResponse.model_validate(signature)


@router.get(
    "/subjects/{subject_id}/signatures",
    response_model=PaginatedResponse[SignatureResponse],
)
async def list_subject_signatures(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: PermissionSvc,
    pagination: Annotated[PaginationParams, Depends()],
) -> Any:
    """List subject- and form-level signatures belonging to a subject."""
    subject = await _get_subject(session, subject_id)
    _require_subject_access(current_user, permission_service, subject, "form.read")

    object_ids = select(FormInstance.id).where(FormInstance.subject_id == subject.id)
    query = select(Signature).where(
        (Signature.object_type == "subject")
        & (Signature.object_id == subject.id)
        | (
            (Signature.object_type == "form")
            & Signature.object_id.in_(object_ids)
        )
    ).order_by(Signature.signed_at.desc())
    total = await session.scalar(
        select(func.count()).select_from(query.subquery())
    )
    signatures = list(
        (
            await session.execute(
                query.offset(pagination.offset).limit(pagination.page_size)
            )
        ).scalars().all()
    )
    return {
        "items": [SignatureResponse.model_validate(signature) for signature in signatures],
        "page": pagination.page,
        "page_size": pagination.page_size,
        "total": int(total or 0),
    }


__all__ = ["router"]
