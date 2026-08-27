"""Audit routes — search, entity-scoped trails, and export.

Thin route handlers that delegate to AuditService for audit event
search, entity-scoped audit trails, and bulk export.

Satisfies Requirements:
  - 18.5: Search filterable by user, date, entity, subject, field.
  - 18.6: Export selected audit events.
  - 21.1: All endpoints mounted under /api/v1.
  - 21.2: List endpoints return a pagination envelope.

Endpoints:
  - GET  /audit-events                           search audit events (audit.read)
  - GET  /subjects/{subject_id}/audit            subject audit trail (audit.read)
  - GET  /form-instances/{form_instance_id}/audit  form instance audit (audit.read) — also in form_data
  - GET  /fields/{field_id}/audit                field audit trail (audit.read)
  - POST /audit-events/export                    export audit events (audit.read)
"""

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.models.identity import User
from app.schemas.audit import AuditEventResponse, AuditSearchFilters
from app.schemas.base import PaginatedResponse

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Main audit router (mounted at /audit-events)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get(
    "",
    response_model=PaginatedResponse[AuditEventResponse],
)
async def search_audit_events(
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("audit.read"))],
    pagination: Annotated[PaginationParams, Depends()],
    actor_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    study_id: UUID | None = None,
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
    field_name: str | None = None,
    action: str | None = None,
    request_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Any:
    """Search audit events with optional filters (paginated).

    Permission: audit.read
    Requirement 18.5: Filterable by user, date, entity, subject, field.
    Requirement 21.2: Paginated response envelope.
    """
    filters = AuditSearchFilters(
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        study_id=study_id,
        site_id=site_id,
        subject_id=subject_id,
        field_name=field_name,
        action=action,
        request_id=request_id,
        date_from=date_from,
        date_to=date_to,
    )

    return await audit_service.search(
        session, filters=filters, pagination=pagination
    )


@router.post(
    "/export",
    response_model=list[dict[str, Any]],
)
async def export_audit_events(
    body: AuditSearchFilters,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("audit.read"))],
) -> list[dict[str, Any]]:
    """Export audit events matching filters as flat dictionaries.

    Permission: audit.read
    Requirement 18.6: Export selected audit events.

    Unlike search, returns ALL matching events (no pagination) as flat
    dictionaries suitable for CSV/Excel/JSON export.
    """
    return await audit_service.export(session, filters=body)


# ---------------------------------------------------------------------------
# Entity-scoped audit trail routes
# ---------------------------------------------------------------------------

subjects_audit_router = APIRouter(prefix="/subjects", tags=["audit"])


@subjects_audit_router.get(
    "/{subject_id}/audit",
    response_model=PaginatedResponse[AuditEventResponse],
)
async def get_subject_audit(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("audit.read"))],
    pagination: Annotated[PaginationParams, Depends()],
) -> Any:
    """Get the audit trail for a subject.

    Permission: audit.read
    Returns paginated audit events scoped to this subject, ordered by
    most recent first.
    """
    filters = AuditSearchFilters(subject_id=subject_id)
    return await audit_service.search(
        session, filters=filters, pagination=pagination
    )


fields_audit_router = APIRouter(prefix="/fields", tags=["audit"])


@fields_audit_router.get(
    "/{field_id}/audit",
    response_model=PaginatedResponse[AuditEventResponse],
)
async def get_field_audit(
    field_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("audit.read"))],
    pagination: Annotated[PaginationParams, Depends()],
) -> Any:
    """Get the audit trail for a field.

    Permission: audit.read
    Returns paginated audit events for this field entity, ordered by
    most recent first.
    """
    filters = AuditSearchFilters(entity_type="field_value", entity_id=field_id)
    return await audit_service.search(
        session, filters=filters, pagination=pagination
    )
