"""PV safety case intake, capture, lifecycle, and version routes.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``Safety_Case_Service`` for validation, canonical identity resolution, and the
atomic Safety_Data + PV safety Audit_Event transaction boundary. Handlers only
validate input, enforce permissions through the shared PV guard, and delegate;
all database access goes through PV repositories inside the service layer.

No route here creates, allocates, or mutates an EDC clinical record (a
Study_Version, Clinical_Subject_Registry record, Visit_Instance, Form_Instance,
Field_Value, Query, SDV/review, freeze/lock, clinical signature,
Clinical_Attachment, or clinical export) or a CTMS operational record; the
service ownership guard rejects any such payload before a transaction opens.
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
from app.models.pv.safety_case import CaseState
from app.repositories.pv.export_repository import PVExportRepository
from app.repositories.pv.safety_case_repository import SafetyCaseRepository
from app.schemas.pv.contracts import PVPaginatedResponse, PVPaginationParams
from app.schemas.pv.resources import (
    AdverseEventCreate,
    AdverseEventResponse,
    CaseChangeRequest,
    CaseTransitionRequest,
    CaseVersionResponse,
    SafetyCaseCreate,
    SafetyCaseResponse,
)
from app.services.safety_case_service import safety_case_service

router = APIRouter(tags=["pv-cases"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]
EnterGuard = Annotated[User, Depends(require_pv_permission("safety_case.enter"))]
LifecycleGuard = Annotated[User, Depends(require_pv_permission("safety_case.lifecycle"))]


@router.post("/cases", response_model=SafetyCaseResponse, status_code=201)
async def create_case(
    body: SafetyCaseCreate,
    session: DbSession,
    current_user: EnterGuard,
) -> SafetyCaseResponse:
    """Open exactly one Safety_Case bound to canonical Study/Site/Subject."""

    payload = body.model_dump(exclude_none=True)
    case = await safety_case_service.create_case(
        session,
        study_id=body.study_id,
        site_id=body.site_id,
        subject_reference=body.subject_reference,
        case_type=body.case_type,
        payload=payload,
        actor=build_actor(current_user),
    )
    return SafetyCaseResponse.model_validate(case)


@router.get("/cases", response_model=PVPaginatedResponse[SafetyCaseResponse])
async def list_cases(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PVPaginationParams, Depends()],
    site_id: UUID | None = None,
    subject_reference: UUID | None = None,
    status: CaseState | None = None,
) -> PVPaginatedResponse[SafetyCaseResponse]:
    """List in-scope Safety_Cases for a study with intersecting filters."""

    repository = PVExportRepository(session)
    cases = await repository.select_cases(
        study_id=study_id,
        site_id=site_id,
        subject_reference=subject_reference,
        case_statuses=[status.value] if status is not None else None,
    )
    start = pagination.offset
    window = cases[start : start + pagination.page_size]
    return PVPaginatedResponse[SafetyCaseResponse](
        items=[SafetyCaseResponse.model_validate(case) for case in window],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(cases),
    )


@router.get("/cases/{case_id}", response_model=SafetyCaseResponse)
async def get_case(
    case_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> SafetyCaseResponse:
    """Return one Safety_Case by identifier."""

    repository = SafetyCaseRepository(session)
    case = await repository.get_case(case_id)
    if case is None:
        raise NotFoundError(
            message="Safety_Case was not found",
            details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
        )
    return SafetyCaseResponse.model_validate(case)


@router.post(
    "/cases/{case_id}/adverse-events",
    response_model=AdverseEventResponse,
    status_code=201,
)
async def add_adverse_event(
    case_id: UUID,
    body: AdverseEventCreate,
    session: DbSession,
    current_user: EnterGuard,
) -> AdverseEventResponse:
    """Capture one Adverse_Event_Record under an existing Safety_Case."""

    record = await safety_case_service.add_adverse_event(
        session,
        case_id=case_id,
        payload=body.model_dump(exclude_none=True),
        actor=build_actor(current_user),
    )
    return AdverseEventResponse.model_validate(record)


@router.get(
    "/cases/{case_id}/adverse-events",
    response_model=PVPaginatedResponse[AdverseEventResponse],
)
async def list_adverse_events(
    case_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PVPaginationParams, Depends()],
) -> PVPaginatedResponse[AdverseEventResponse]:
    """List the Adverse_Event_Records captured under a Safety_Case."""

    repository = SafetyCaseRepository(session)
    events = await repository.list_adverse_events(case_id)
    start = pagination.offset
    window = events[start : start + pagination.page_size]
    return PVPaginatedResponse[AdverseEventResponse](
        items=[AdverseEventResponse.model_validate(event) for event in window],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(events),
    )


@router.post("/cases/{case_id}/transition", response_model=SafetyCaseResponse)
async def transition_case(
    case_id: UUID,
    body: CaseTransitionRequest,
    session: DbSession,
    current_user: LifecycleGuard,
) -> SafetyCaseResponse:
    """Move a Safety_Case to a new lifecycle state if permitted."""

    case = await safety_case_service.transition(
        session,
        case_id=case_id,
        target=body.target,
        reason=body.reason,
        actor=build_actor(current_user),
    )
    return SafetyCaseResponse.model_validate(case)


@router.post(
    "/cases/{case_id}/versions",
    response_model=CaseVersionResponse,
    status_code=201,
)
async def submit_version(
    case_id: UUID,
    session: DbSession,
    current_user: LifecycleGuard,
) -> CaseVersionResponse:
    """Submit an immutable initial or follow-up Case_Version snapshot."""

    version = await safety_case_service.submit_version(
        session,
        case_id=case_id,
        actor=build_actor(current_user),
    )
    return CaseVersionResponse.model_validate(version)


@router.post("/cases/{case_id}/changes", response_model=SafetyCaseResponse)
async def change_submitted_data(
    case_id: UUID,
    body: CaseChangeRequest,
    session: DbSession,
    current_user: EnterGuard,
) -> SafetyCaseResponse:
    """Apply a post-submission change with a required Reason_For_Change."""

    changes = body.model_dump(exclude_none=True, exclude={"reason_for_change"})
    case = await safety_case_service.change_submitted_data(
        session,
        case_id=case_id,
        changes=changes,
        reason_for_change=body.reason_for_change,
        actor=build_actor(current_user),
    )
    return SafetyCaseResponse.model_validate(case)
