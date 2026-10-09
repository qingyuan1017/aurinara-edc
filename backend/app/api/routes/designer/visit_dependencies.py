"""Visit dependency authoring routes — Designer-owned.

Handlers for authoring ``Visit_Definition_Dependency`` edges (visit-to-visit
dependencies, which also cover cycle dependencies) inside a Draft_Design,
delegating to the Designer ``visit_dependency_service``.

Endpoints:
  - GET  /visits/{visit_id}/dependencies   list a visit's dependency edges
  - POST /visits/{visit_id}/dependencies   create a visit dependency edge
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.visit_dependency import (
    VisitDependencyCreate,
    VisitDependencyResponse,
)
from app.services.designer.visit_dependency_service import visit_dependency_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/visits", tags=["designer-visit-dependencies"])


@router.post(
    "/{visit_id}/dependencies",
    response_model=VisitDependencyResponse,
    status_code=201,
)
async def create_visit_dependency(
    visit_id: UUID,
    body: VisitDependencyCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.visit.configure"))],
) -> VisitDependencyResponse:
    """Create a visit-to-visit dependency edge.

    Permission: designer.visit.configure (Designer_Role only)
    """
    dependency = await visit_dependency_service.create_dependency(
        session,
        visit_definition_id=visit_id,
        depends_on_visit_definition_id=body.depends_on_visit_definition_id,
        dependency_type=body.dependency_type,
        condition_expression=body.condition_expression,
        actor_id=current_user.id,
    )
    return VisitDependencyResponse.model_validate(dependency)


@router.get(
    "/{visit_id}/dependencies",
    response_model=list[VisitDependencyResponse],
)
async def list_visit_dependencies(
    visit_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.visit.read"))],
) -> list[VisitDependencyResponse]:
    """List a visit's dependency edges.

    Permission: designer.visit.read (Designer_Role only)
    """
    return [
        VisitDependencyResponse.model_validate(dep)
        for dep in await visit_dependency_service.list_dependencies(session, visit_id)
    ]


__all__ = ["router"]
