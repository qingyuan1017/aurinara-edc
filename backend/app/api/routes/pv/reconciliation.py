"""PV EDC adverse-event reconciliation routes.

Reconciliation is one-way and read-only over the approved, minimized EDC
adverse-event projection; no route here mutates an EDC clinical record or a CTMS
operational record. Thin, authenticated handlers delegate to the
``Reconciliation_Service``, which owns diffing, the study-scope check, and the
atomic PV reconciliation + PV safety Audit_Event transaction boundary.
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
from app.repositories.pv.reconciliation_repository import ReconciliationRepository
from app.schemas.pv.resources import (
    ReconciliationDiscrepancyResponse,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
)
from app.services.reconciliation_service import reconciliation_service

router = APIRouter(tags=["pv-reconciliation"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
RunGuard = Annotated[User, Depends(require_pv_permission("safety_reconciliation.run"))]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]


@router.post(
    "/reconciliation/runs",
    response_model=ReconciliationRunResponse,
    status_code=201,
)
async def run_reconciliation(
    body: ReconciliationRunRequest,
    session: DbSession,
    current_user: RunGuard,
) -> ReconciliationRunResponse:
    """Reconcile Safety_Cases against the read-only EDC projection for a study."""

    run = await reconciliation_service.run(
        session,
        study_id=body.study_id,
        actor=build_actor(current_user),
    )
    return ReconciliationRunResponse.model_validate(run)


@router.get("/reconciliation/runs/{run_id}", response_model=ReconciliationRunResponse)
async def get_run(
    run_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> ReconciliationRunResponse:
    """Return one reconciliation run by identifier."""

    repository = ReconciliationRepository(session)
    run = await repository.get_run(run_id)
    if run is None:
        raise NotFoundError(
            message="Reconciliation run was not found",
            details={"reason": "RECORD_NOT_FOUND", "entity_type": "reconciliation_run"},
        )
    return ReconciliationRunResponse.model_validate(run)


@router.post(
    "/reconciliation/discrepancies/{discrepancy_id}/resolve",
    response_model=ReconciliationDiscrepancyResponse,
)
async def resolve_discrepancy(
    discrepancy_id: UUID,
    session: DbSession,
    current_user: RunGuard,
) -> ReconciliationDiscrepancyResponse:
    """Mark a Reconciliation_Discrepancy resolved (PV-owned state only)."""

    discrepancy = await reconciliation_service.resolve(
        session,
        discrepancy_id=discrepancy_id,
        actor=build_actor(current_user),
    )
    return ReconciliationDiscrepancyResponse.model_validate(discrepancy)
