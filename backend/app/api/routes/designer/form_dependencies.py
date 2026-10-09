"""Form dependency authoring routes — Designer-owned.

Handlers for authoring ``Form_Definition_Dependency`` edges (form-to-form
dependencies) inside a Draft_Design, delegating to the Designer
``form_dependency_service``.

Endpoints:
  - GET  /forms/{form_id}/dependencies   list a form's dependency edges
  - POST /forms/{form_id}/dependencies   create a form dependency edge
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.form_dependency import (
    FormDependencyCreate,
    FormDependencyResponse,
)
from app.services.designer.form_dependency_service import form_dependency_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/forms", tags=["designer-form-dependencies"])


@router.post(
    "/{form_id}/dependencies",
    response_model=FormDependencyResponse,
    status_code=201,
)
async def create_form_dependency(
    form_id: UUID,
    body: FormDependencyCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.form.configure"))],
) -> FormDependencyResponse:
    """Create a form-to-form dependency edge.

    Permission: designer.form.configure (Designer_Role only)
    """
    dependency = await form_dependency_service.create_dependency(
        session,
        form_definition_id=form_id,
        depends_on_form_definition_id=body.depends_on_form_definition_id,
        dependency_type=body.dependency_type,
        condition_expression=body.condition_expression,
        actor_id=current_user.id,
    )
    return FormDependencyResponse.model_validate(dependency)


@router.get(
    "/{form_id}/dependencies",
    response_model=list[FormDependencyResponse],
)
async def list_form_dependencies(
    form_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.form.read"))],
) -> list[FormDependencyResponse]:
    """List a form's dependency edges.

    Permission: designer.form.read (Designer_Role only)
    """
    return [
        FormDependencyResponse.model_validate(dep)
        for dep in await form_dependency_service.list_dependencies(session, form_id)
    ]


__all__ = ["router"]
