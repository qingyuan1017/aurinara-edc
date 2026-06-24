"""Site routes — site CRUD and site-level user assignment.

Satisfies Requirements:
  - 6.1: Persist site metadata (site number, name, PI, country, region, address, status).
  - 6.4: Deactivate site (set status inactive, retain record).
  - 6.5: Record site-level user assignment.
  - 21.1: All endpoints mounted under /api/v1.
  - 21.2: List endpoints return a pagination envelope.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.site import (
    SiteCreate,
    SiteResponse,
    SiteUpdate,
    SiteUserAssign,
    SiteUserResponse,
)
from app.services.site_service import site_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study-scoped site collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_sites_router = APIRouter(prefix="/studies", tags=["sites"])


@study_sites_router.get(
    "/{study_id}/sites", response_model=PaginatedResponse[SiteResponse]
)
async def list_sites(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.read"))],
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[SiteResponse]:
    """List sites for a study (paginated).

    Permission: site.read
    Requirement 21.2: Paginated response envelope.
    """
    result = await site_service.list_sites(session, study_id, pagination)
    return PaginatedResponse[SiteResponse](
        items=[SiteResponse.model_validate(s) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_sites_router.post(
    "/{study_id}/sites", response_model=SiteResponse, status_code=201
)
async def create_site(
    study_id: UUID,
    body: SiteCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.manage"))],
) -> SiteResponse:
    """Create a new site within a study.

    Permission: site.manage
    Requirement 6.1: Persist site metadata.
    """
    site = await site_service.create_site(
        session=session, study_id=study_id, data=body, actor_id=current_user.id
    )
    return SiteResponse.model_validate(site)


# ---------------------------------------------------------------------------
# Single-site operations (mounted at /sites)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("/{site_id}", response_model=SiteResponse)
async def get_site(
    site_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.read"))],
) -> SiteResponse:
    """Get a site by ID.

    Permission: site.read
    """
    site = await site_service.get_site(session, site_id)
    return SiteResponse.model_validate(site)


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: UUID,
    body: SiteUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.manage"))],
) -> SiteResponse:
    """Update site metadata (partial PATCH).

    Permission: site.manage
    Requirement 6.1: Site metadata changes write Audit_Events.
    """
    site = await site_service.get_site(session, site_id)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return SiteResponse.model_validate(site)

    for field_name, new_value in update_data.items():
        old_value = getattr(site, field_name, None)
        setattr(site, field_name, new_value)

        if old_value != new_value:
            await audit_service.record(
                session,
                entity_type="site",
                entity_id=site.id,
                action="update",
                study_id=site.study_id,
                site_id=site.id,
                actor_id=current_user.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
            )

    site.updated_at = datetime.now(UTC)
    await session.flush()

    logger.info("Site updated: id=%s actor=%s", site.id, current_user.id)
    return SiteResponse.model_validate(site)


@router.delete("/{site_id}", response_model=SiteResponse)
async def deactivate_site(
    site_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.manage"))],
) -> SiteResponse:
    """Deactivate a site (set status inactive, retain the record).

    Permission: site.manage
    Requirement 6.4: Deactivation retains the record.
    """
    site = await site_service.get_site(session, site_id)
    deactivated = await site_service.deactivate_site(
        session=session, site=site, actor_id=current_user.id
    )
    return SiteResponse.model_validate(deactivated)


@router.post("/{site_id}/users", response_model=SiteUserResponse, status_code=201)
async def assign_user_to_site(
    site_id: UUID,
    body: SiteUserAssign,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("site.manage"))],
) -> SiteUserResponse:
    """Assign a user to a site within its study.

    Permission: site.manage
    Requirement 6.5: Record site-level user assignment.
    """
    site = await site_service.get_site(session, site_id)
    assignment = await site_service.assign_user(
        session=session,
        study_id=site.study_id,
        site_id=site.id,
        user_id=body.user_id,
        actor_id=current_user.id,
    )
    return SiteUserResponse.model_validate(assignment)
