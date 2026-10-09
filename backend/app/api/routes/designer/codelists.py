"""Codelist authoring routes — Designer-owned controlled vocabularies.

Codelists are Designer_Definitions split out of the combined EDC form metadata
into the Designer module. These handlers delegate to the Designer
``codelist_service`` and operate only while the owning Design_Version is a
draft.

Satisfies Requirements:
  - 6.1: Create a codelist (name + 1-1000 items) within a Draft_Design.

Endpoints:
  - GET  /studies/{study_id}/codelists   list codelists (designer.codelist.read)
  - POST /studies/{study_id}/codelists   create codelist (designer.codelist.configure)
  - GET  /codelists/{codelist_id}        get codelist (designer.codelist.read)
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.exceptions import NotFoundError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.shared.identity import User
from app.schemas.edc.form_metadata import CodelistCreate, CodelistResponse
from app.services.designer.codelist_service import codelist_service
from app.services.edc.study_service import study_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _get_latest_or_specified_version(
    session: AsyncSession,
    study_id: UUID,
    study_version_id: UUID | None = None,
) -> StudyVersion:
    """Return the specified version, or the latest draft version for the study."""
    if study_version_id is not None:
        result = await session.execute(
            select(StudyVersion).where(
                StudyVersion.id == study_version_id,
                StudyVersion.study_id == study_id,
            )
        )
        version = result.scalars().first()
        if version is None:
            raise NotFoundError(
                "Study version not found",
                details={
                    "study_version_id": str(study_version_id),
                    "study_id": str(study_id),
                },
            )
        return version

    result = await session.execute(
        select(StudyVersion)
        .where(
            StudyVersion.study_id == study_id,
            StudyVersion.status == StudyVersionStatus.draft,
        )
        .order_by(StudyVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalars().first()
    if version is None:
        raise NotFoundError(
            "No draft study version found for this study",
            details={"study_id": str(study_id)},
        )
    return version


# Study-scoped codelist collection (mounted at /studies)
study_codelists_router = APIRouter(prefix="/studies", tags=["designer-codelists"])

# Single codelist operations (mounted at /codelists)
router = APIRouter(prefix="/codelists", tags=["designer-codelists"])


@study_codelists_router.get(
    "/{study_id}/codelists", response_model=list[CodelistResponse]
)
async def list_codelists(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.codelist.read"))],
    study_version_id: Annotated[
        UUID | None,
        Query(description="Specific study version ID. Defaults to the latest draft."),
    ] = None,
) -> list[CodelistResponse]:
    """List codelists for a study's specified or latest draft version.

    Permission: designer.codelist.read (Designer_Role only)
    """
    await study_service.get_study(session, study_id)
    version = await _get_latest_or_specified_version(session, study_id, study_version_id)
    codelists = await codelist_service.list_codelists(session, version.id)
    return [CodelistResponse.model_validate(c) for c in codelists]


@study_codelists_router.post(
    "/{study_id}/codelists", response_model=CodelistResponse, status_code=201
)
async def create_codelist(
    study_id: UUID,
    body: CodelistCreate,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.codelist.configure"))
    ],
    study_version_id: Annotated[
        UUID | None,
        Query(description="Target study version ID. Defaults to the latest draft."),
    ] = None,
) -> CodelistResponse:
    """Create a codelist (with items) on a draft Design_Version.

    Permission: designer.codelist.configure (Designer_Role only)
    """
    await study_service.get_study(session, study_id)
    version = await _get_latest_or_specified_version(session, study_id, study_version_id)
    codelist = await codelist_service.create_codelist(
        session=session, version=version, data=body, actor_id=current_user.id
    )
    return CodelistResponse.model_validate(codelist)


@router.get("/{codelist_id}", response_model=CodelistResponse)
async def get_codelist(
    codelist_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.codelist.read"))],
) -> CodelistResponse:
    """Get a codelist with its items.

    Permission: designer.codelist.read (Designer_Role only)
    """
    codelist = await codelist_service.get_codelist(session, codelist_id)
    return CodelistResponse.model_validate(codelist)


__all__ = ["router", "study_codelists_router"]
