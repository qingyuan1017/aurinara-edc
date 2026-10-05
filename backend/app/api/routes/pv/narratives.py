"""PV case-narrative routes and history.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``Narrative_Service``. The service validates narrative text and
Reason_For_Change, enforces the Closed-case guard, retains prior versions
immutably, and owns the atomic Safety_Data + PV safety Audit_Event transaction
boundary. No route mutates an EDC clinical or CTMS operational record.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.core.exceptions import NotFoundError
from app.models.identity import User
from app.repositories.pv.narrative_repository import NarrativeRepository
from app.schemas.pv.contracts import PVPaginatedResponse, PVPaginationParams
from app.schemas.pv.resources import (
    NarrativeCreate,
    NarrativeResponse,
    NarrativeRevise,
    NarrativeVersionResponse,
)
from app.services.narrative_service import narrative_service

router = APIRouter(tags=["pv-narratives"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]
WriteGuard = Annotated[User, Depends(require_pv_permission("safety_narrative.write"))]


@router.post(
    "/cases/{case_id}/narratives",
    response_model=NarrativeResponse,
    status_code=201,
)
async def create_narrative(
    case_id: UUID,
    body: NarrativeCreate,
    session: DbSession,
    current_user: WriteGuard,
) -> NarrativeResponse:
    """Author a new Case_Narrative for a Safety_Case."""

    narrative = await narrative_service.create(
        session,
        case_id=case_id,
        text=body.text,
        actor=build_actor(current_user),
    )
    return NarrativeResponse.model_validate(narrative)


@router.post("/narratives/{narrative_id}/revisions", response_model=NarrativeVersionResponse)
async def revise_narrative(
    narrative_id: UUID,
    body: NarrativeRevise,
    session: DbSession,
    current_user: WriteGuard,
) -> NarrativeVersionResponse:
    """Revise a Case_Narrative, retaining the prior version immutably."""

    version = await narrative_service.revise(
        session,
        narrative_id=narrative_id,
        text=body.text,
        reason_for_change=body.reason_for_change,
        actor=build_actor(current_user),
    )
    return NarrativeVersionResponse.model_validate(version)


@router.get("/narratives/{narrative_id}", response_model=NarrativeResponse)
async def get_narrative(
    narrative_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> NarrativeResponse:
    """Return one Case_Narrative (current text) by identifier."""

    repository = NarrativeRepository(session)
    narrative = await repository.get_narrative(narrative_id)
    if narrative is None:
        raise NotFoundError(
            message="Case_Narrative was not found",
            details={"reason": "RECORD_NOT_FOUND", "entity_type": "case_narrative"},
        )
    return NarrativeResponse.model_validate(narrative)


@router.get(
    "/narratives/{narrative_id}/versions",
    response_model=PVPaginatedResponse[NarrativeVersionResponse],
)
async def list_narrative_versions(
    narrative_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PVPaginationParams, Depends()],
) -> PVPaginatedResponse[NarrativeVersionResponse]:
    """Return the retained Case_Narrative version history."""

    repository = NarrativeRepository(session)
    versions = await repository.list_versions(narrative_id)
    start = pagination.offset
    window = versions[start : start + pagination.page_size]
    return PVPaginatedResponse[NarrativeVersionResponse](
        items=[NarrativeVersionResponse.model_validate(v) for v in window],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(versions),
    )
