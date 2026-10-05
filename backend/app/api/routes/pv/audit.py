"""PV safety audit search and export routes.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``PV_Audit_Service``. Both endpoints require ``safety_audit.read`` and are
scoped to the caller's Authorization_Scope: an out-of-scope search or export is
rejected without disclosing any Audit_Event (Requirements 11.4, 11.8).

Search supports exact filtering by user, inclusive UTC date range, entity,
Safety_Case, and Regulatory_Report, and returns PV safety Audit_Events ordered
by UTC timestamp ascending with ties broken by Audit_Event identifier ascending
(Requirement 11.4). Export produces exactly the authorized selected events and
records the export action (Requirement 11.5). PV safety Audit_Events are
immutable; this router exposes no update or delete route for an Audit_Event
(Requirement 11.6). No route mutates an EDC clinical or CTMS operational record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.models.identity import User
from app.schemas.pv.audit import (
    PVAuditEventResponse,
    PVAuditExportRequest,
    PVAuditExportResponse,
    PVAuditSearchFilters,
)
from app.schemas.pv.contracts import PVPaginatedResponse, PVPaginationParams
from app.services.pv_audit_service import pv_audit_service

router = APIRouter(tags=["pv-audit"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
AuditReadGuard = Annotated[User, Depends(require_pv_permission("safety_audit.read"))]


@router.get(
    "/audit/events",
    response_model=PVPaginatedResponse[PVAuditEventResponse],
)
async def search_audit_events(
    session: DbSession,
    current_user: AuditReadGuard,
    pagination: Annotated[PVPaginationParams, Depends()],
    actor_id: Annotated[UUID | None, Query(description="Exact acting-user filter")] = None,
    entity_type: Annotated[
        str | None, Query(max_length=100, description="Exact PV entity-type filter")
    ] = None,
    safety_case_id: Annotated[
        UUID | None, Query(description="Audit_Events for this Safety_Case")
    ] = None,
    regulatory_report_id: Annotated[
        UUID | None, Query(description="Audit_Events for this Regulatory_Report")
    ] = None,
    study_id: Annotated[UUID | None, Query(description="Study scope filter")] = None,
    site_id: Annotated[UUID | None, Query(description="Site scope filter")] = None,
    date_from: Annotated[
        datetime | None, Query(description="Inclusive UTC lower bound")
    ] = None,
    date_to: Annotated[
        datetime | None, Query(description="Inclusive UTC upper bound")
    ] = None,
) -> PVPaginatedResponse[PVAuditEventResponse]:
    """Search in-scope PV safety Audit_Events with deterministic ordering."""

    filters = PVAuditSearchFilters(
        actor_id=actor_id,
        entity_type=entity_type,
        safety_case_id=safety_case_id,
        regulatory_report_id=regulatory_report_id,
        study_id=study_id,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )
    return await pv_audit_service.search(
        session, user=current_user, filters=filters, pagination=pagination
    )


@router.post(
    "/audit/exports",
    response_model=PVAuditExportResponse,
    status_code=201,
)
async def export_audit_events(
    body: PVAuditExportRequest,
    session: DbSession,
    current_user: AuditReadGuard,
) -> PVAuditExportResponse:
    """Export exactly the authorized selected PV safety Audit_Events.

    The export records one PV safety Audit_Event for the export action and never
    updates or deletes an existing Audit_Event (Requirements 11.5, 11.6).
    """

    return await pv_audit_service.export(
        session,
        user=current_user,
        actor=build_actor(current_user),
        filters=body.filters,
    )
