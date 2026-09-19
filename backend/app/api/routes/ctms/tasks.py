"""Authenticated CTMS operational task routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.work import OperationalTask, OperationalTaskStatus
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.work import (
    QueryFollowUpCreate,
    TaskCreate,
    TaskResponse,
    TaskStatusChange,
    TaskUpdate,
)
from app.services.work_management_service import work_management_service

router = APIRouter(tags=["ctms-tasks"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]


@router.get("/studies/{study_id}/tasks", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: OperationalTaskStatus | None = None,
):
    conditions = [OperationalTask.study_id == study_id, OperationalTask.deleted_at.is_(None)]
    if site_id is not None:
        conditions.append(OperationalTask.site_id == site_id)
    if status is not None:
        conditions.append(OperationalTask.status == status.value)
    total = int(
        await session.scalar(select(func.count()).select_from(OperationalTask).where(*conditions))
        or 0
    )
    rows = await session.scalars(
        select(OperationalTask)
        .where(*conditions)
        .order_by(OperationalTask.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return PaginatedResponse(
        items=[TaskResponse.model_validate(x) for x in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.post("/studies/{study_id}/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    study_id: UUID, body: TaskCreate, session: DbSession, current_user: WriteGuard
):
    if body.study_id != study_id:
        from app.core.exceptions import ValidationError

        raise ValidationError("study_id in the path and body must match")
    return TaskResponse.model_validate(
        await work_management_service.create_task(
            session, body, current_user.id, correlation_id=get_correlation_id()
        )
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, session: DbSession, current_user: ReadGuard):
    task = await work_management_service._resolve_task(session, task_id)
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID, body: TaskUpdate, session: DbSession, current_user: WriteGuard
):
    return TaskResponse.model_validate(
        await work_management_service.update_task(
            session, task_id, body, current_user.id, correlation_id=get_correlation_id()
        )
    )


@router.post("/tasks/{task_id}/transition", response_model=TaskResponse)
async def transition_task(
    task_id: UUID, body: TaskStatusChange, session: DbSession, current_user: WriteGuard
):
    return TaskResponse.model_validate(
        await work_management_service.transition_task_status(
            session,
            task_id,
            body.status,
            current_user.id,
            reason=body.reason,
            correlation_id=get_correlation_id(),
        )
    )


__all__ = ["router"]


@router.post("/queries/{query_id}/follow-ups", response_model=TaskResponse, status_code=201)
async def create_query_follow_up(
    query_id: UUID, body: QueryFollowUpCreate, session: DbSession, current_user: WriteGuard
):
    task = await work_management_service.create_query_follow_up(
        session,
        query_id=query_id,
        actor_id=current_user.id,
        title=body.title,
        approved_summary=body.approved_summary,
        owner_id=body.owner_id,
        due_date=body.due_date,
        priority=body.priority,
        correlation_id=get_correlation_id(),
    )
    return TaskResponse.model_validate(task)
