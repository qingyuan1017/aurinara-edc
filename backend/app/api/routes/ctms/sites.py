"""Authenticated CTMS operational site and activation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.site import (
    ActivationActionCompletion,
    ActivationActionCreate,
    ActivationActionResponse,
    ActivationActionStatusChange,
    OperationalSiteProfileCreate,
    OperationalSiteProfileUpdate,
    OperationalSiteResponse,
    OperationalSiteStatusChange,
)
from app.services.operational_site_service import operational_site_service

router = APIRouter(prefix="/sites", tags=["ctms-sites"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-site-management"))]


@router.get("/{site_id}/operational-profile", response_model=OperationalSiteResponse)
async def get_operational_site(site_id: UUID, session: DbSession, current_user: ReadGuard):
    return OperationalSiteResponse.model_validate(
        await operational_site_service.get_profile(session, site_id)
    )


@router.post(
    "/{site_id}/operational-profile", response_model=OperationalSiteResponse, status_code=201
)
async def create_operational_site(
    site_id: UUID, body: OperationalSiteProfileCreate, session: DbSession, current_user: WriteGuard
):
    return OperationalSiteResponse.model_validate(
        await operational_site_service.create_profile(
            session,
            site_id=site_id,
            payload=body,
            actor=current_user,
            study_id=body.study_id,
            correlation_id=get_correlation_id(),
        )
    )


@router.patch("/operational-sites/{profile_id}", response_model=OperationalSiteResponse)
async def update_operational_site(
    profile_id: UUID,
    body: OperationalSiteProfileUpdate,
    session: DbSession,
    current_user: WriteGuard,
    reason: str | None = Query(default=None),
):
    return OperationalSiteResponse.model_validate(
        await operational_site_service.update_profile(
            session,
            profile_id,
            body,
            actor=current_user,
            reason=reason,
            correlation_id=get_correlation_id(),
        )
    )


@router.post("/operational-sites/{profile_id}/transition", response_model=OperationalSiteResponse)
async def transition_operational_site(
    profile_id: UUID,
    body: OperationalSiteStatusChange,
    session: DbSession,
    current_user: WriteGuard,
):
    return OperationalSiteResponse.model_validate(
        await operational_site_service.transition_status(
            session,
            profile_id,
            body.status,
            body.reason,
            actor=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.get("/{site_id}/activation", response_model=PaginatedResponse[ActivationActionResponse])
async def list_activation_actions(
    site_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    include_archived: bool = False,
):
    actions = await operational_site_service.list_activation_actions(
        session, site_id, include_archived=include_archived
    )
    page = actions[pagination.offset : pagination.offset + pagination.page_size]
    return PaginatedResponse(
        items=[ActivationActionResponse.model_validate(item) for item in page],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(actions),
    )


@router.post("/{site_id}/activation", response_model=ActivationActionResponse, status_code=201)
async def create_activation_action(
    site_id: UUID, body: ActivationActionCreate, session: DbSession, current_user: WriteGuard
):
    return ActivationActionResponse.model_validate(
        await operational_site_service.create_activation_action(
            session,
            site_id=site_id,
            payload=body,
            study_id=body.study_id if hasattr(body, "study_id") else None,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.post("/activation-actions/{action_id}/transition", response_model=ActivationActionResponse)
async def transition_activation_action(
    action_id: UUID,
    body: ActivationActionStatusChange,
    session: DbSession,
    current_user: WriteGuard,
):
    return ActivationActionResponse.model_validate(
        await operational_site_service.transition_activation_action(
            session,
            action_id,
            body.status,
            body.reason,
            actor=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.post("/activation-actions/{action_id}/complete", response_model=ActivationActionResponse)
async def complete_activation_action(
    action_id: UUID, body: ActivationActionCompletion, session: DbSession, current_user: WriteGuard
):
    return ActivationActionResponse.model_validate(
        await operational_site_service.complete_activation_action(
            session,
            action_id,
            body.evidence_reference,
            actor=current_user,
            reason=body.reason,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


__all__ = ["router"]


operational_sites_router = APIRouter(prefix="/operational-sites", tags=["ctms-sites"])
operational_sites_router.add_api_route(
    "/{profile_id}",
    update_operational_site,
    methods=["PATCH"],
    response_model=OperationalSiteResponse,
)
operational_sites_router.add_api_route(
    "/{profile_id}/transition",
    transition_operational_site,
    methods=["POST"],
    response_model=OperationalSiteResponse,
)
activation_actions_router = APIRouter(prefix="/activation-actions", tags=["ctms-sites"])
activation_actions_router.add_api_route(
    "/{action_id}/transition",
    transition_activation_action,
    methods=["POST"],
    response_model=ActivationActionResponse,
)
activation_actions_router.add_api_route(
    "/{action_id}/complete",
    complete_activation_action,
    methods=["POST"],
    response_model=ActivationActionResponse,
)
