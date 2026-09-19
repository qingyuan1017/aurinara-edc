"""Authenticated CTMS operational study and planning routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.operational_study import (
    EnrollmentPlan,
    StudyOperationalMilestone,
    StudyPlan,
)
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.dashboard import DashboardQueryCreate, DashboardQueryResponse
from app.schemas.ctms.report import ReportQueryCreate, ReportQueryResponse
from app.schemas.ctms.study import (
    EnrollmentPlanCreate,
    EnrollmentPlanResponse,
    OperationalMilestoneCreate,
    OperationalStudyArchive,
    OperationalStudyCreate,
    OperationalStudyResponse,
    OperationalStudyStatusChange,
    OperationalStudyUpdate,
    ReadinessCriterionCreate,
    ReadinessCriterionResponse,
    StudyOperationalMilestoneResponse,
    StudyPlanCreate,
    StudyPlanResponse,
)
from app.services.operational_study_service import operational_study_service

router = APIRouter(prefix="/studies", tags=["ctms-studies"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]


async def _page(session: AsyncSession, model, where, pagination: PaginationParams):
    count = await session.scalar(select(func.count()).select_from(model).where(*where))
    rows = await session.scalars(
        select(model)
        .where(*where)
        .order_by(model.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=list(rows),
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(count or 0),
    )


@router.get("/{study_id}/operational-profile", response_model=OperationalStudyResponse)
async def get_operational_profile(study_id: UUID, session: DbSession, current_user: ReadGuard):
    return OperationalStudyResponse.model_validate(
        await operational_study_service.get_profile(session, study_id)
    )


@router.post(
    "/{study_id}/operational-profile", response_model=OperationalStudyResponse, status_code=201
)
async def create_operational_profile(
    study_id: UUID, body: OperationalStudyCreate, session: DbSession, current_user: WriteGuard
):
    profile = await operational_study_service.create_profile(
        session,
        study_id=study_id,
        payload=body,
        actor=current_user,
        correlation_id=get_correlation_id(),
    )
    return OperationalStudyResponse.model_validate(profile)


@router.patch("/operational-studies/{profile_id}", response_model=OperationalStudyResponse)
async def update_operational_profile(
    profile_id: UUID,
    body: OperationalStudyUpdate,
    session: DbSession,
    current_user: WriteGuard,
    reason: str | None = Query(default=None),
):
    profile = await operational_study_service.update_profile(
        session,
        profile_id,
        body,
        actor=current_user,
        reason=reason,
        correlation_id=get_correlation_id(),
    )
    return OperationalStudyResponse.model_validate(profile)


@router.post(
    "/operational-studies/{profile_id}/transition", response_model=OperationalStudyResponse
)
async def transition_operational_profile(
    profile_id: UUID,
    body: OperationalStudyStatusChange,
    session: DbSession,
    current_user: WriteGuard,
):
    profile = await operational_study_service.transition_status(
        session,
        profile_id,
        body.status,
        body.reason,
        actor=current_user,
        correlation_id=body.correlation_id or get_correlation_id(),
    )
    return OperationalStudyResponse.model_validate(profile)


@router.post("/operational-studies/{profile_id}/archive", response_model=OperationalStudyResponse)
async def archive_operational_profile(
    profile_id: UUID, body: OperationalStudyArchive, session: DbSession, current_user: WriteGuard
):
    profile = await operational_study_service.archive_study(
        session,
        profile_id,
        actor=current_user,
        reason=body.reason,
        correlation_id=body.correlation_id or get_correlation_id(),
    )
    return OperationalStudyResponse.model_validate(profile)


@router.get("/{study_id}/plans", response_model=PaginatedResponse[StudyPlanResponse])
async def list_study_plans(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    result = await _page(session, StudyPlan, [StudyPlan.study_id == study_id], pagination)
    return PaginatedResponse(
        items=[StudyPlanResponse.model_validate(x) for x in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@router.post("/{study_id}/plans", response_model=StudyPlanResponse, status_code=201)
async def create_study_plan(
    study_id: UUID, body: StudyPlanCreate, session: DbSession, current_user: WriteGuard
):
    return StudyPlanResponse.model_validate(
        await operational_study_service.create_study_plan(
            session,
            study_id=study_id,
            payload=body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/{study_id}/enrollment-plans", response_model=PaginatedResponse[EnrollmentPlanResponse]
)
async def list_enrollment_plans(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    result = await _page(session, EnrollmentPlan, [EnrollmentPlan.study_id == study_id], pagination)
    return PaginatedResponse(
        items=[EnrollmentPlanResponse.model_validate(x) for x in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@router.post("/{study_id}/enrollment-plans", response_model=EnrollmentPlanResponse, status_code=201)
async def create_enrollment_plan(
    study_id: UUID, body: EnrollmentPlanCreate, session: DbSession, current_user: WriteGuard
):
    return EnrollmentPlanResponse.model_validate(
        await operational_study_service.create_enrollment_plan(
            session,
            study_id=study_id,
            payload=body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.post(
    "/{study_id}/readiness-criteria", response_model=ReadinessCriterionResponse, status_code=201
)
async def create_readiness_criterion(
    study_id: UUID, body: ReadinessCriterionCreate, session: DbSession, current_user: WriteGuard
):
    return ReadinessCriterionResponse.model_validate(
        await operational_study_service.create_readiness_criterion(
            session,
            study_id=study_id,
            payload=body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/{study_id}/milestones", response_model=PaginatedResponse[StudyOperationalMilestoneResponse]
)
async def list_study_milestones(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    result = await _page(
        session,
        StudyOperationalMilestone,
        [StudyOperationalMilestone.study_id == study_id],
        pagination,
    )
    return PaginatedResponse(
        items=[StudyOperationalMilestoneResponse.model_validate(x) for x in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@router.post(
    "/{study_id}/milestones", response_model=StudyOperationalMilestoneResponse, status_code=201
)
async def create_study_milestone(
    study_id: UUID, body: OperationalMilestoneCreate, session: DbSession, current_user: WriteGuard
):
    return StudyOperationalMilestoneResponse.model_validate(
        await operational_study_service.create_operational_milestone(
            session,
            study_id=study_id,
            payload=body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.post(
    "/{study_id}/dashboard-queries", response_model=DashboardQueryResponse, status_code=201
)
async def create_dashboard_query(
    study_id: UUID, body: DashboardQueryCreate, session: DbSession, current_user: WriteGuard
):
    return DashboardQueryResponse.model_validate(
        await operational_study_service.create_dashboard_query(
            session,
            study_id=study_id,
            payload=body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.post("/{study_id}/report-queries", response_model=ReportQueryResponse, status_code=201)
async def create_report_query(
    study_id: UUID, body: ReportQueryCreate, session: DbSession, current_user: WriteGuard
):
    return ReportQueryResponse.model_validate(
        await operational_study_service.create_report_query(
            session,
            study_id=study_id,
            payload=body,
            actor=current_user,
            correlation_id=get_correlation_id(),
        )
    )


__all__ = ["router"]


# Root-level aliases match the public CTMS contract while the study collection
# router above keeps study-scoped resources grouped in OpenAPI.
operational_studies_router = APIRouter(prefix="/operational-studies", tags=["ctms-studies"])
operational_studies_router.add_api_route(
    "/{profile_id}",
    update_operational_profile,
    methods=["PATCH"],
    response_model=OperationalStudyResponse,
)
operational_studies_router.add_api_route(
    "/{profile_id}/transition",
    transition_operational_profile,
    methods=["POST"],
    response_model=OperationalStudyResponse,
)
operational_studies_router.add_api_route(
    "/{profile_id}/archive",
    archive_operational_profile,
    methods=["POST"],
    response_model=OperationalStudyResponse,
)
