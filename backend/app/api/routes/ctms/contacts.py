"""Authenticated CTMS operational contact routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.work import OperationalContact, OperationalContactStatus
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.work import ContactCreate, ContactResponse, ContactStatusChange
from app.services.work_management_service import work_management_service

router = APIRouter(tags=["ctms-contacts"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]


@router.get("/studies/{study_id}/contacts", response_model=PaginatedResponse[ContactResponse])
async def list_contacts(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: OperationalContactStatus | None = None,
):
    conditions = [OperationalContact.study_id == study_id, OperationalContact.deleted_at.is_(None)]
    if site_id is not None:
        conditions.append(OperationalContact.site_id == site_id)
    if status is not None:
        conditions.append(OperationalContact.status == status.value)
    total = int(
        await session.scalar(
            select(func.count()).select_from(OperationalContact).where(*conditions)
        )
        or 0
    )
    rows = await session.scalars(
        select(OperationalContact)
        .where(*conditions)
        .order_by(OperationalContact.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[ContactResponse.model_validate(x) for x in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.post("/studies/{study_id}/contacts", response_model=ContactResponse, status_code=201)
async def create_contact(
    study_id: UUID, body: ContactCreate, session: DbSession, current_user: WriteGuard
):
    if body.study_id != study_id:
        from app.core.exceptions import ValidationError

        raise ValidationError("study_id in the path and body must match")
    return ContactResponse.model_validate(
        await work_management_service.create_contact(
            session, body, current_user.id, correlation_id=get_correlation_id()
        )
    )


@router.get("/contacts/{contact_id}", response_model=ContactResponse)
async def get_contact(contact_id: UUID, session: DbSession, current_user: ReadGuard):
    contact = await work_management_service._resolve_contact(session, contact_id)
    return ContactResponse.model_validate(contact)


@router.post("/contacts/{contact_id}/transition", response_model=ContactResponse)
async def transition_contact(
    contact_id: UUID, body: ContactStatusChange, session: DbSession, current_user: WriteGuard
):
    return ContactResponse.model_validate(
        await work_management_service.transition_contact_status(
            session,
            contact_id,
            body.status,
            current_user.id,
            reason=body.reason,
            correlation_id=get_correlation_id(),
        )
    )
