"""PV safety audit search and export service.

The PV audit trail is not a second audit store: it is the shared, immutable
append-only ``Audit_Service`` primitive filtered to PV safety Audit_Events
(``module="PV"``). This service adds the PV-specific *read* concerns on top of
that primitive:

  * scoping every search/export to the caller's resolved ``Authorization_Scope``
    so only in-scope PV safety Audit_Events are returned or exported, and an
    out-of-scope search/export is rejected without disclosing any event
    (Requirements 11.4, 11.8);
  * exact filtering by user, inclusive UTC date range, entity, Safety_Case, and
    Regulatory_Report (Requirement 11.4);
  * deterministic ordering by UTC timestamp ascending with ties broken by
    Audit_Event identifier ascending (Requirement 11.4);
  * producing an export containing exactly the authorized selected events and
    recording the export action via the shared PV atomicity helper
    (Requirement 11.5).

Audit_Events are immutable. This service exposes no update or delete path; the
model layer additionally rejects any mutation (Requirement 11.6).
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.pv import ActorContext, Module
from app.models.audit import AuditEvent
from app.models.identity import User
from app.schemas.permission import AuthorizationScope
from app.schemas.pv.audit import (
    PVAuditEventResponse,
    PVAuditExportResponse,
    PVAuditExportRow,
    PVAuditSearchFilters,
)
from app.schemas.pv.contracts import PVPaginatedResponse, PVPaginationParams
from app.services.permission_service import PermissionService
from app.services.pv_atomicity_service import pv_atomicity_service

_SAFETY_AUDIT_READ = "safety_audit.read"


class PVAuditService:
    """Scoped, deterministically ordered PV safety audit reads and exports."""

    def __init__(self, permission_service: PermissionService | None = None) -> None:
        self._permissions = permission_service or PermissionService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        session: AsyncSession,
        *,
        user: User,
        filters: PVAuditSearchFilters,
        pagination: PVPaginationParams,
    ) -> PVPaginatedResponse[PVAuditEventResponse]:
        """Return a page of in-scope PV safety Audit_Events.

        Events are ordered by UTC timestamp ascending, ties broken by
        Audit_Event identifier ascending. A search whose explicit study/site
        filter falls outside the caller's Authorization_Scope is rejected and
        returns no event (Requirements 11.4, 11.8).
        """

        scope = self._authorize(user, filters)
        query = self._build_query(scope, filters)

        count_query = select(func.count()).select_from(query.subquery())
        total = int((await session.execute(count_query)).scalar_one())

        page_query = query.limit(pagination.page_size).offset(pagination.offset)
        rows = (await session.execute(page_query)).scalars().all()

        return PVPaginatedResponse[PVAuditEventResponse](
            items=[PVAuditEventResponse.model_validate(row) for row in rows],
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
        )

    async def export(
        self,
        session: AsyncSession,
        *,
        user: User,
        actor: ActorContext,
        filters: PVAuditSearchFilters,
    ) -> PVAuditExportResponse:
        """Export exactly the authorized selected PV safety Audit_Events.

        The selection uses the same scope and filters as :meth:`search` and the
        same deterministic order (no pagination). The export action is recorded
        as one PV safety Audit_Event in the caller's transaction (Requirement
        11.5). An out-of-scope export is rejected and produces nothing
        (Requirement 11.8).
        """

        scope = self._authorize(user, filters)
        query = self._build_query(scope, filters)
        rows = (await session.execute(query)).scalars().all()

        events = [
            PVAuditExportRow(
                id=str(row.id),
                actor_id=str(row.actor_id) if row.actor_id else None,
                actor_email=row.actor_email,
                timestamp=row.timestamp.isoformat(),
                entity_type=row.entity_type,
                entity_id=str(row.entity_id),
                study_id=str(row.study_id) if row.study_id else None,
                site_id=str(row.site_id) if row.site_id else None,
                subject_id=str(row.subject_id) if row.subject_id else None,
                module=row.module if isinstance(row.module, str) else Module.PV.value,
                action=row.action,
                correlation_id=(
                    row.correlation_id if isinstance(row.correlation_id, str) else None
                ),
                changed_fields=(
                    row.changed_fields if isinstance(row.changed_fields, list) else None
                ),
                field_name=row.field_name,
                old_value=row.old_value,
                new_value=row.new_value,
                reason=row.reason,
                request_id=str(row.request_id),
            )
            for row in rows
        ]

        export_id = uuid4()
        # Record the export action as a PV safety Audit_Event in this
        # transaction. The action targets the export operation itself, not any
        # single Safety_Case, and never mutates an existing Audit_Event.
        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_audit_export",
            entity_id=export_id,
            action="export",
            actor=actor,
            study_id=filters.study_id,
            site_id=filters.site_id,
            new_value=len(events),
        )

        return PVAuditExportResponse(
            export_id=export_id, total=len(events), events=events
        )

    # ------------------------------------------------------------------
    # Scope and query helpers
    # ------------------------------------------------------------------

    def _authorize(
        self, user: User, filters: PVAuditSearchFilters
    ) -> AuthorizationScope:
        """Resolve the caller's scope and reject out-of-scope search/export.

        The caller must hold ``safety_audit.read`` at the requested study/site
        scope. When no explicit study/site filter is supplied a system-scope
        grant is required, so a study/site-scoped user cannot read across the
        whole PV audit trail. A denial does not disclose whether any event
        exists (Requirement 11.8).
        """

        try:
            self._permissions.require(
                user,
                _SAFETY_AUDIT_READ,
                study_id=filters.study_id,
                site_id=filters.site_id,
            )
        except AuthorizationError:
            raise AuthorizationError(
                message="Access denied",
                details={
                    "reason": "PV_SCOPE_DENIED",
                    "required_permission": _SAFETY_AUDIT_READ,
                },
            ) from None

        scope = self._permissions.resolve_scope(user)

        # A caller without a system-scope grant must constrain the search to a
        # study within their scope; an unscoped search would otherwise leak
        # out-of-scope events.
        if not scope.has_system_grant() and filters.study_id is None:
            raise AuthorizationError(
                message="Access denied",
                details={
                    "reason": "PV_SCOPE_DENIED",
                    "required_permission": _SAFETY_AUDIT_READ,
                },
            )

        return scope

    def _build_query(
        self, scope: AuthorizationScope, filters: PVAuditSearchFilters
    ) -> Select[tuple[AuditEvent]]:
        """Build the scoped, filtered, deterministically ordered query.

        The base predicate restricts to PV safety Audit_Events. Non-system
        callers are additionally restricted to the studies within their scope so
        the result contains only in-scope events even without an explicit
        study filter (defense in depth alongside :meth:`_authorize`).
        """

        query = select(AuditEvent).where(AuditEvent.module == Module.PV.value)

        if not scope.has_system_grant():
            allowed_study_ids = list(scope.get_study_ids())
            if not allowed_study_ids:
                # No study grants: the caller can see no PV audit events.
                query = query.where(false())
            else:
                query = query.where(AuditEvent.study_id.in_(allowed_study_ids))

        query = self._apply_filters(query, filters)

        # Deterministic order: UTC timestamp ascending, ties broken by
        # Audit_Event identifier ascending (Requirement 11.4).
        return query.order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())

    @staticmethod
    def _apply_filters(
        query: Select[tuple[AuditEvent]], filters: PVAuditSearchFilters
    ) -> Select[tuple[AuditEvent]]:
        """Apply the exact PV audit search filters (Requirement 11.4)."""

        if filters.actor_id is not None:
            query = query.where(AuditEvent.actor_id == filters.actor_id)
        if filters.entity_type is not None:
            query = query.where(AuditEvent.entity_type == filters.entity_type)
        if filters.study_id is not None:
            query = query.where(AuditEvent.study_id == filters.study_id)
        if filters.site_id is not None:
            query = query.where(AuditEvent.site_id == filters.site_id)
        # Safety_Case / Regulatory_Report select Audit_Events recorded directly
        # against that entity. Both are matched by (entity_type, entity_id).
        if filters.safety_case_id is not None:
            query = query.where(
                AuditEvent.entity_type == "safety_case",
                AuditEvent.entity_id == filters.safety_case_id,
            )
        if filters.regulatory_report_id is not None:
            query = query.where(
                AuditEvent.entity_type == "regulatory_report",
                AuditEvent.entity_id == filters.regulatory_report_id,
            )
        if filters.date_from is not None:
            query = query.where(AuditEvent.timestamp >= filters.date_from)
        if filters.date_to is not None:
            query = query.where(AuditEvent.timestamp <= filters.date_to)
        return query


pv_audit_service = PVAuditService()

__all__ = ["PVAuditService", "pv_audit_service"]
