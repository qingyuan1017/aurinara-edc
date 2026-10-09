"""Design_Version authoring routes — Designer-owned version lifecycle.

Moved from ``app.api.routes.edc.studies`` as part of the Designer / EDC refactor.
Only the **design-authoring** version lifecycle moves here: creating a draft
Design_Version, amending a published version into a new draft, and publishing a
draft. Study identity CRUD and operational study reads stay in the EDC module.

The handlers keep authorization and version ownership server-side while
delegating lifecycle rules to the Designer ``study_version_service``.

Satisfies Requirements:
  - 2.1: Create and publish a draft Design_Version (draft -> published).
  - 2.9: Amend a published version with a reason, creating one new draft.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.study_version import (
    StudyAmendmentCreate,
    StudyVersionCreate,
    StudyVersionResponse,
)
from app.services.designer.study_version_service import study_version_service
from app.services.edc.study_service import study_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

# Study-scoped version authoring (mounted at /studies)
study_versions_router = APIRouter(prefix="/studies", tags=["designer-versions"])

# Version lifecycle operations keyed by version id (mounted at /versions)
versions_router = APIRouter(prefix="/versions", tags=["designer-versions"])


@study_versions_router.post(
    "/{study_id}/versions", response_model=StudyVersionResponse, status_code=201
)
async def create_version(
    study_id: UUID,
    body: StudyVersionCreate,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.study_version.create"))
    ],
) -> StudyVersionResponse:
    """Create a new draft Design_Version for a study.

    Permission: designer.study_version.create (Designer_Role only)
    Requirement 2.1: Create a new draft Design_Version.
    """
    # Ensure the study exists before authoring a version against it.
    await study_service.get_study(session, study_id)

    version = await study_version_service.create_version(
        session=session,
        study_id=study_id,
        version_number=body.version_number,
        amendment_reason=body.amendment_reason,
        actor_id=current_user.id,
    )
    return StudyVersionResponse.model_validate(version)


@study_versions_router.post(
    "/{study_id}/amend", response_model=StudyVersionResponse, status_code=201
)
async def create_amendment(
    study_id: UUID,
    body: StudyAmendmentCreate,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.study_version.amend"))
    ],
) -> StudyVersionResponse:
    """Create a draft amendment from the latest published version.

    Permission: designer.study_version.amend (Designer_Role only)
    Requirement 2.9: Amend a published version, creating exactly one new draft.
    """
    study = await study_service.get_study(session, study_id)
    version = await study_version_service.create_amendment(
        session=session,
        study=study,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return StudyVersionResponse.model_validate(version)


@versions_router.post("/{version_id}/publish", response_model=StudyVersionResponse)
async def publish_version(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.version.publish"))
    ],
) -> StudyVersionResponse:
    """Publish a draft Design_Version (draft -> published).

    Permission: designer.version.publish (Designer_Role only)
    Requirement 2.1: Transition draft -> published, recording actor and timestamp.
    """
    version = await study_version_service.get_version(session, version_id)
    published = await study_version_service.publish(
        session=session, version=version, actor_id=current_user.id
    )
    return StudyVersionResponse.model_validate(published)


__all__ = ["study_versions_router", "versions_router"]
