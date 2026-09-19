"""Authenticated CTMS monitoring plan and activity routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityStatus,
    MonitoringPlan,
)
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.monitoring import (
    MonitoringActivityAssign,
    MonitoringActivityCancel,
    MonitoringActivityComplete,
    MonitoringActivityCreate,
    MonitoringActivityReschedule,
    MonitoringActivityResponse,
    MonitoringPlanAmend,
    MonitoringPlanCreate,
    MonitoringPlanResponse,
    MonitoringPlanUpdate,
    MonitoringPlanVersionResponse,
)
from app.services.monitoring_service import monitoring_service

router = APIRouter(tags=["ctms-monitoring"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[
    User, Depends(require_ctms_permission("ctms.monitoring-activity-management"))
]


@router.get(
    "/studies/{study_id}/monitoring-plans", response_model=PaginatedResponse[MonitoringPlanResponse]
)
async def list_monitoring_plans(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(MonitoringPlan)
            .where(MonitoringPlan.study_id == study_id)
        )
        or 0
    )
    rows = await session.scalars(
        select(MonitoringPlan)
        .where(MonitoringPlan.study_id == study_id)
        .order_by(MonitoringPlan.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[MonitoringPlanResponse.model_validate(x) for x in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.post(
    "/studies/{study_id}/monitoring-plans", response_model=MonitoringPlanResponse, status_code=201
)
async def create_monitoring_plan(
    study_id: UUID, body: MonitoringPlanCreate, session: DbSession, current_user: WriteGuard
):
    return MonitoringPlanResponse.model_validate(
        await monitoring_service.create_plan(
            session,
            study_id=study_id,
            payload=body,
            site_id=body.site_id,
            actor=current_user,
            user=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.get(
    "/monitoring-plans/{plan_id}/versions",
    response_model=PaginatedResponse[MonitoringPlanVersionResponse],
)
async def list_monitoring_plan_versions(
    plan_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    versions = await monitoring_service.list_versions(session, plan_id)
    page = versions[pagination.offset : pagination.offset + pagination.page_size]
    return PaginatedResponse(
        items=[MonitoringPlanVersionResponse.model_validate(x) for x in page],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(versions),
    )


@router.patch("/monitoring-plans/{plan_id}", response_model=MonitoringPlanResponse)
async def update_monitoring_plan(
    plan_id: UUID, body: MonitoringPlanUpdate, session: DbSession, current_user: WriteGuard
):
    return MonitoringPlanResponse.model_validate(
        await monitoring_service.update_plan(
            session,
            plan_id,
            body,
            actor=current_user,
            user=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.post("/monitoring-plans/{plan_id}/publish", response_model=MonitoringPlanVersionResponse)
async def publish_monitoring_plan(plan_id: UUID, session: DbSession, current_user: WriteGuard):
    return MonitoringPlanVersionResponse.model_validate(
        await monitoring_service.publish_plan(
            session,
            plan_id,
            actor=current_user,
            user=current_user,
            correlation_id=get_correlation_id(),
        )
    )


@router.post("/monitoring-plans/{plan_id}/amend", response_model=MonitoringPlanVersionResponse)
async def amend_monitoring_plan(
    plan_id: UUID, body: MonitoringPlanAmend, session: DbSession, current_user: WriteGuard
):
    return MonitoringPlanVersionResponse.model_validate(
        await monitoring_service.amend_plan(
            session,
            plan_id,
            body.changes,
            reason=body.reason,
            actor=current_user,
            user=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.get(
    "/studies/{study_id}/monitoring-activities",
    response_model=PaginatedResponse[MonitoringActivityResponse],
)
async def list_monitoring_activities(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: MonitoringActivityStatus | None = None,
):
    conditions = [MonitoringActivity.study_id == study_id]
    if site_id is not None:
        conditions.append(MonitoringActivity.site_id == site_id)
    if status is not None:
        conditions.append(MonitoringActivity.status == status.value)
    total = int(
        await session.scalar(
            select(func.count()).select_from(MonitoringActivity).where(*conditions)
        )
        or 0
    )
    rows = await session.scalars(
        select(MonitoringActivity)
        .where(*conditions)
        .order_by(MonitoringActivity.planned_date.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[MonitoringActivityResponse.model_validate(x) for x in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.post(
    "/studies/{study_id}/monitoring-activities",
    response_model=MonitoringActivityResponse,
    status_code=201,
)
async def schedule_monitoring_activity(
    study_id: UUID, body: MonitoringActivityCreate, session: DbSession, current_user: WriteGuard
):
    activity = await monitoring_service.schedule_activity(
        session,
        plan=body.plan_id,
        payload=body.model_dump(exclude={"plan_id"}),
        activity_type=body.activity_type,
        planned_date=body.planned_date,
        assigned_cra_id=body.assigned_cra_id,
        edc_visit_instance_id=body.edc_visit_instance_id,
        actor=current_user,
        user=current_user,
        correlation_id=body.correlation_id or get_correlation_id(),
    )
    return MonitoringActivityResponse.model_validate(activity)


@router.post(
    "/monitoring-activities/{activity_id}/assign", response_model=MonitoringActivityResponse
)
async def assign_monitoring_activity(
    activity_id: UUID, body: MonitoringActivityAssign, session: DbSession, current_user: WriteGuard
):
    return MonitoringActivityResponse.model_validate(
        await monitoring_service.assign_activity(
            session,
            activity_id,
            body.assigned_cra_id,
            actor=current_user,
            user=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.post(
    "/monitoring-activities/{activity_id}/reschedule", response_model=MonitoringActivityResponse
)
async def reschedule_monitoring_activity(
    activity_id: UUID,
    body: MonitoringActivityReschedule,
    session: DbSession,
    current_user: WriteGuard,
):
    return MonitoringActivityResponse.model_validate(
        await monitoring_service.reschedule_activity(
            session,
            activity_id,
            body.planned_date,
            body.reason,
            actor=current_user,
            user=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.post(
    "/monitoring-activities/{activity_id}/complete", response_model=MonitoringActivityResponse
)
async def complete_monitoring_activity(
    activity_id: UUID,
    body: MonitoringActivityComplete,
    session: DbSession,
    current_user: WriteGuard,
):
    return MonitoringActivityResponse.model_validate(
        await monitoring_service.complete_activity(
            session,
            activity_id,
            body.evidence,
            body.notes,
            actor=current_user,
            user=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )


@router.post(
    "/monitoring-activities/{activity_id}/cancel", response_model=MonitoringActivityResponse
)
async def cancel_monitoring_activity(
    activity_id: UUID, body: MonitoringActivityCancel, session: DbSession, current_user: WriteGuard
):
    return MonitoringActivityResponse.model_validate(
        await monitoring_service.cancel_activity(
            session,
            activity_id,
            body.reason,
            actor=current_user,
            user=current_user,
            correlation_id=body.correlation_id or get_correlation_id(),
        )
    )
