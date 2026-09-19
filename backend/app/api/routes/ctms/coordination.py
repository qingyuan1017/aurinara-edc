"""Authenticated, sanitized CTMS coordination and remediation routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.audit import audit_service
from app.models.ctms.coordination import CTMSOutbox
from app.models.ctms.retention import CTMSCoordinationConflict, CTMSFailedEvent
from app.models.identity import User
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.coordination import (
    ConflictResolveRequest,
    CoordinationConflictResponse,
    CoordinationEventResponse,
    CoordinationReplayRequest,
    FailedEventResponse,
)
from app.services.coordination_service import coordination_service

router = APIRouter(tags=["ctms-coordination"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
ReplayGuard = Annotated[User, Depends(require_ctms_permission("ctms.coordination-replay"))]
ConflictGuard = Annotated[User, Depends(require_ctms_permission("ctms.conflict-management"))]


def _utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite's naive timestamp values for the UTC API contract."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event(row: CTMSOutbox) -> CoordinationEventResponse:
    payload = dict(row.payload_json or {})
    return CoordinationEventResponse(
        id=row.id,
        event_id=row.event_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        source_module=row.source_module,
        target_module=row.target_module,
        status=row.status,
        correlation_id=row.correlation_id,
        source_version=row.source_version or (
            str(payload.get("source_version"))
            if payload.get("source_version") is not None
            else None
        ),
        source_sequence=row.source_sequence,
        current_version=row.current_version,
        rule_version=row.rule_version or payload.get("rule_version"),
        resulting_projection_id=row.resulting_projection_id,
        outcome=row.outcome,
        reason=row.last_error_category,
        accepted_at=_utc(row.available_at),
        processed_at=_utc(row.published_at),
    )


@router.get(
    "/studies/{study_id}/coordination-events",
    response_model=PaginatedResponse[CoordinationEventResponse],
)
async def list_coordination_events(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows = list(
        (await session.scalars(select(CTMSOutbox).order_by(CTMSOutbox.available_at.desc()))).all()
    )
    rows = [row for row in rows if str((row.payload_json or {}).get("study_id")) == str(study_id)]
    page = rows[pagination.offset : pagination.offset + pagination.page_size]
    return PaginatedResponse(
        items=[_event(row) for row in page],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(rows),
    )


@router.get("/coordination-events/{event_id}", response_model=CoordinationEventResponse)
async def get_coordination_event(event_id: UUID, session: DbSession, current_user: ReadGuard):
    from app.core.exceptions import NotFoundError

    row = await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event_id))
    if row is None:
        raise NotFoundError("Coordination event was not found", {"event_id": str(event_id)})
    return _event(row)


@router.post("/coordination-events/{event_id}/replay", response_model=CoordinationEventResponse)
async def replay_coordination_event(
    event_id: UUID, body: CoordinationReplayRequest, session: DbSession, current_user: ReplayGuard
):
    row = await coordination_service.replay_failed_event(
        session, event_id=event_id, actor=current_user, reason=body.reason
    )
    return _event(row)


@router.get(
    "/studies/{study_id}/failed-events", response_model=PaginatedResponse[FailedEventResponse]
)
async def list_failed_events(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows = list(
        (
            await session.scalars(
                select(CTMSFailedEvent)
                .where(CTMSFailedEvent.study_id == study_id, CTMSFailedEvent.deleted_at.is_(None))
                .order_by(CTMSFailedEvent.created_at.desc())
            )
        ).all()
    )
    page = rows[pagination.offset : pagination.offset + pagination.page_size]
    return PaginatedResponse(
        items=[
            FailedEventResponse(
                id=row.id,
                event_id=row.event_id,
                event_type="coordination",
                source_module="CTMS",
                status="Failed",
                reason_code=row.reason_code,
                sanitized_details=dict(row.sanitized_details_json or {}),
                correlation_id=row.correlation_id,
                created_at=row.created_at,
                updated_at=None,
            )
            for row in page
        ],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(rows),
    )


@router.get(
    "/studies/{study_id}/coordination-conflicts",
    response_model=PaginatedResponse[CoordinationConflictResponse],
)
async def list_coordination_conflicts(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows = list(
        (
            await session.scalars(
                select(CTMSCoordinationConflict)
                .where(
                    CTMSCoordinationConflict.study_id == study_id,
                    CTMSCoordinationConflict.deleted_at.is_(None),
                )
                .order_by(CTMSCoordinationConflict.created_at.desc())
            )
        ).all()
    )
    page = rows[pagination.offset : pagination.offset + pagination.page_size]
    return PaginatedResponse(
        items=[
            CoordinationConflictResponse(
                id=row.id,
                event_id=row.event_id,
                entity_type="coordination",
                field_path=row.field_path,
                conflict_type=row.conflict_type,
                source_version=row.source_version,
                current_version=row.current_version,
                policy=row.policy,
                status=row.status,
                sanitized_details=dict(row.sanitized_details_json or {}),
                correlation_id=row.correlation_id or "",
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )
            for row in page
        ],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(rows),
    )


@router.post(
    "/coordination-conflicts/{conflict_id}/resolve", response_model=CoordinationConflictResponse
)
async def resolve_coordination_conflict(
    conflict_id: UUID, body: ConflictResolveRequest, session: DbSession, current_user: ConflictGuard
):
    from app.core.exceptions import NotFoundError, ValidationError

    row = await session.scalar(
        select(CTMSCoordinationConflict).where(CTMSCoordinationConflict.id == conflict_id)
    )
    if row is None:
        raise NotFoundError("Coordination conflict was not found", {"conflict_id": str(conflict_id)})
    policy = body.policy.strip().lower()
    if policy not in {"keep_current", "apply_source", "skip_event"}:
        raise ValidationError("Conflict resolution policy is not supported", {"reason": "INVALID_RESOLUTION_POLICY"})
    row.policy = policy
    row.status = "resolved"
    row.resolved_at = datetime.now(UTC)
    row.sanitized_details_json = {"reason_code": "RESOLVED", "policy": policy}
    if row.event_id is not None and policy == "apply_source":
        outbox = await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == row.event_id))
        if outbox is not None:
            outbox.status = "Pending"
            outbox.outcome = None
            outbox.last_error_category = None
            outbox.sanitized_reason = None
            outbox.available_at = datetime.now(UTC)
    await session.flush()
    await audit_service.record(
        session,
        entity_type="coordination_conflict",
        entity_id=row.id,
        action="resolve",
        module="CTMS",
        actor_id=current_user.id,
        correlation_id=row.correlation_id,
        source_record_id=row.event_id,
        study_id=row.study_id,
        site_id=row.site_id,
        changed_fields=["status", "policy", "resolved_at"],
        reason=body.reason.strip()[:160],
    )
    return CoordinationConflictResponse(
        id=row.id,
        event_id=row.event_id,
        entity_type="coordination",
        field_path=row.field_path,
        conflict_type=row.conflict_type,
        source_version=row.source_version,
        current_version=row.current_version,
        policy=row.policy,
        status=row.status,
        sanitized_details=dict(row.sanitized_details_json or {}),
        correlation_id=row.correlation_id or "",
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )
