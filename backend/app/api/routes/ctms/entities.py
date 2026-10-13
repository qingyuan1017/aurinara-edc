"""CTMS entity catalog and study-assignment routes."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.config import get_settings
from app.core.request_context import get_correlation_id
from app.models.ctms.entity_management import (
    ManagedEntity,
    ManagedEntityType,
    StudyEntityAssignment,
)
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User
from app.schemas.ctms.entity_management import (
    ManagedEntityCreate,
    ManagedEntityResponse,
    ManagedEntityUpdate,
    ManagedSiteCreate,
    StudyEntityAssignmentCreate,
    StudyEntityAssignmentResponse,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.ctms.entity_management_service import entity_management_service
from app.services.shared.platform_authorization import get_platform_authorization

router = APIRouter(tags=["ctms-entity-management"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]
SiteWriteGuard = Annotated[
    User, Depends(require_ctms_permission("ctms.operational-site-management"))
]


@router.post(
    "/studies/{study_id}/sites",
    response_model=ManagedEntityResponse,
    status_code=201,
)
async def create_site(
    study_id: UUID,
    body: ManagedSiteCreate,
    session: DbSession,
    current_user: SiteWriteGuard,
) -> ManagedEntityResponse:
    """Create a CTMS-owned Site and synchronize its generated ID to the platform."""

    entity = await entity_management_service.create_site(
        session,
        study_id,
        body,
        actor=current_user,
        correlation_id=get_correlation_id(),
    )
    settings = get_settings()
    study = await session.get(Study, study_id)
    should_sync = settings.platform_authorization_mode == "enforced" or (
        settings.platform_authorization_mode == "shadow"
        and study is not None
        and study.platform_managed
    )
    if should_sync:
        await asyncio.to_thread(
            get_platform_authorization().sync_site,
            study_id=study_id,
            site_id=entity.id,
            name=entity.name,
            country=body.country,
            state=body.state,
            city=body.city,
        )
    return ManagedEntityResponse.model_validate(entity)


@router.get("/entities", response_model=PaginatedResponse[ManagedEntityResponse])
async def list_entities(
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    entity_type: Annotated[ManagedEntityType | None, Query()] = None,
    active: Annotated[bool | None, Query()] = True,
):
    where = [ManagedEntity.deleted_at.is_(None)]
    if entity_type is not None:
        where.append(ManagedEntity.entity_type == entity_type.value)
    if active is not None:
        where.append(ManagedEntity.active.is_(active))
    total = await session.scalar(select(func.count()).select_from(ManagedEntity).where(*where))
    rows = await session.scalars(
        select(ManagedEntity)
        .where(*where)
        .order_by(ManagedEntity.entity_type, ManagedEntity.name)
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[ManagedEntityResponse.model_validate(row) for row in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(total or 0),
    )


@router.post("/entities", response_model=ManagedEntityResponse, status_code=201)
async def create_entity(body: ManagedEntityCreate, session: DbSession, current_user: WriteGuard):
    return ManagedEntityResponse.model_validate(
        await entity_management_service.create_entity(
            session, body, actor=current_user, correlation_id=get_correlation_id()
        )
    )


@router.get(
    "/studies/{study_id}/available-entities",
    response_model=PaginatedResponse[ManagedEntityResponse],
)
async def list_available_study_entities(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    entity_type: Annotated[ManagedEntityType | None, Query()] = None,
):
    """List active catalog entities through the caller's study scope."""

    where = [
        ManagedEntity.deleted_at.is_(None),
        ManagedEntity.active.is_(True),
        or_(
            ManagedEntity.entity_type != ManagedEntityType.SITE.value,
            and_(Site.study_id == study_id, Site.deleted_at.is_(None)),
        ),
    ]
    if entity_type is not None:
        where.append(ManagedEntity.entity_type == entity_type.value)
    catalog = select(ManagedEntity).outerjoin(Site, Site.id == ManagedEntity.canonical_site_id)
    total = await session.scalar(
        select(func.count())
        .select_from(ManagedEntity)
        .outerjoin(Site, Site.id == ManagedEntity.canonical_site_id)
        .where(*where)
    )
    rows = await session.scalars(
        catalog.where(*where)
        .order_by(ManagedEntity.entity_type, ManagedEntity.name)
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[ManagedEntityResponse.model_validate(row) for row in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(total or 0),
    )


@router.patch("/entities/{entity_id}", response_model=ManagedEntityResponse)
async def update_entity(
    entity_id: UUID, body: ManagedEntityUpdate, session: DbSession, current_user: WriteGuard
):
    entity = await entity_management_service.update_entity(
        session, entity_id, body, actor=current_user, correlation_id=get_correlation_id()
    )
    if entity.entity_type == ManagedEntityType.SITE.value and entity.canonical_site_id is not None:
        site = await session.get(Site, entity.canonical_site_id)
        study = await session.get(Study, site.study_id) if site is not None else None
        settings = get_settings()
        should_sync = settings.platform_authorization_mode == "enforced" or (
            settings.platform_authorization_mode == "shadow"
            and study is not None
            and study.platform_managed
        )
        if should_sync and site is not None:
            await asyncio.to_thread(
                get_platform_authorization().sync_site,
                study_id=site.study_id,
                site_id=site.id,
                name=site.name,
                country=entity.attributes.get("country"),
                state=entity.attributes.get("state"),
                city=entity.attributes.get("city"),
                status=site.status.value if hasattr(site.status, "value") else str(site.status),
            )
    return ManagedEntityResponse.model_validate(entity)


@router.get(
    "/studies/{study_id}/entities",
    response_model=PaginatedResponse[StudyEntityAssignmentResponse],
)
async def list_study_entities(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    entity_type: Annotated[ManagedEntityType | None, Query()] = None,
):
    where = [
        StudyEntityAssignment.study_id == study_id,
        StudyEntityAssignment.deleted_at.is_(None),
    ]
    query = select(StudyEntityAssignment).join(StudyEntityAssignment.entity).where(*where)
    count_query = (
        select(func.count())
        .select_from(StudyEntityAssignment)
        .join(StudyEntityAssignment.entity)
        .where(*where)
    )
    if entity_type is not None:
        query = query.where(ManagedEntity.entity_type == entity_type.value)
        count_query = count_query.where(ManagedEntity.entity_type == entity_type.value)
    total = await session.scalar(count_query)
    rows = await session.scalars(
        query.order_by(ManagedEntity.entity_type, ManagedEntity.name)
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[StudyEntityAssignmentResponse.model_validate(row) for row in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(total or 0),
    )


@router.post(
    "/studies/{study_id}/entities",
    response_model=StudyEntityAssignmentResponse,
    status_code=201,
)
async def assign_study_entity(
    study_id: UUID,
    body: StudyEntityAssignmentCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    return StudyEntityAssignmentResponse.model_validate(
        await entity_management_service.assign_to_study(
            session,
            study_id,
            body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


__all__ = ["router"]
