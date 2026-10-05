"""PV MedDRA and WHODrug coding routes.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``Coding_Service``. The service validates the dictionary version and term
membership, enforces the Closed-case guard, retains prior assignments immutably
on recode, and owns the atomic Safety_Data + PV safety Audit_Event transaction
boundary. No route mutates an EDC clinical or CTMS operational record.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.models.identity import User
from app.schemas.pv.resources import (
    CodingResponse,
    MedDraCodingRequest,
    RecodeRequest,
    WhoDrugCodingRequest,
)
from app.services.coding_service import CodingService

router = APIRouter(tags=["pv-coding"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
CodeGuard = Annotated[User, Depends(require_pv_permission("safety_coding.assign"))]

_coding_service = CodingService()


@router.post(
    "/adverse-events/{ae_id}/meddra-codings",
    response_model=CodingResponse,
    status_code=201,
)
async def assign_meddra(
    ae_id: UUID,
    body: MedDraCodingRequest,
    session: DbSession,
    current_user: CodeGuard,
) -> CodingResponse:
    """Assign a MedDRA coding to an adverse-event verbatim term."""

    coding = await _coding_service.assign_meddra(
        session,
        ae_id=ae_id,
        term_id=body.term_id,
        dictionary_version=body.dictionary_version,
        term_label=body.term_label,
        actor=build_actor(current_user),
    )
    return CodingResponse.model_validate(coding)


@router.post(
    "/whodrug-codings",
    response_model=CodingResponse,
    status_code=201,
)
async def assign_whodrug(
    body: WhoDrugCodingRequest,
    session: DbSession,
    current_user: CodeGuard,
) -> CodingResponse:
    """Assign a WHODrug coding to a reported product."""

    coding = await _coding_service.assign_whodrug(
        session,
        product_id=body.product_id,
        term_id=body.term_id,
        dictionary_version=body.dictionary_version,
        term_label=body.term_label,
        actor=build_actor(current_user),
    )
    return CodingResponse.model_validate(coding)


@router.post(
    "/codings/{prior_coding_id}/recode",
    response_model=CodingResponse,
    status_code=201,
)
async def recode(
    prior_coding_id: UUID,
    body: RecodeRequest,
    session: DbSession,
    current_user: CodeGuard,
) -> CodingResponse:
    """Recode a prior assignment, retaining the prior coding immutably."""

    coding = await _coding_service.recode(
        session,
        prior_coding_id=prior_coding_id,
        term_id=body.term_id,
        dictionary_version=body.dictionary_version,
        term_label=body.term_label,
        actor=build_actor(current_user),
    )
    return CodingResponse.model_validate(coding)
