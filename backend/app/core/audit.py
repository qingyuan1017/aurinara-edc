"""Audit_Service — append-only audit write helper bound to the active transaction.

The AuditService writes Audit_Events within the caller's existing database
transaction (same session), guaranteeing atomic commit/rollback of data + audit.
It auto-populates actor_id and request_id from the request context when available.

Satisfies Requirements:
  - 18.1: Records actor, timestamp, entity, study, site, action, field,
           old/new value, reason, request_id.
  - 18.3: Records Reason_For_Change for post-submission field changes.
  - 18.5: Search filterable by user, date, entity, subject, field.
  - 18.6: Export selected audit events.
  - 21.4: Audit_Event written in the same transaction as the data change.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.ctms import Module, utc_now
from app.core.request_context import get_actor, get_request_id
from app.models.audit import AuditEvent
from app.schemas.audit import AuditEventExport, AuditSearchFilters

logger = logging.getLogger(__name__)


class AuditService:
    """Append-only audit service.

    All write operations occur within the caller's session (transaction),
    ensuring the Audit_Event and the data change commit or roll back together.
    No update or delete methods are exposed (application-layer immutability).
    """

    async def record(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        module: Module | str = Module.EDC,
        actor_kind: str = "user",
        worker_id: str | None = None,
        correlation_id: str | None = None,
        scope: Mapping[str, UUID | str | None] | None = None,
        changed_fields: Sequence[str] | None = None,
        source_module: Module | str | None = None,
        target_module: Module | str | None = None,
        source_record_id: UUID | None = None,
        target_record_id: UUID | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        field_name: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        reason: str | None = None,
        actor_id: UUID | None = None,
        actor_email: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEvent:
        """Record an audit event within the caller's transaction.

        Auto-populates actor_id and request_id from request context if not
        explicitly provided.

        Args:
            session: The active SQLAlchemy async session (caller's transaction).
            entity_type: The type of the affected entity (e.g. "subject", "form_instance").
            entity_id: The primary key of the affected entity.
            action: The action performed (e.g. "create", "update", "delete", "submit").
            study_id: Optional study scope.
            site_id: Optional site scope.
            subject_id: Optional subject scope.
            field_name: Optional field name for field-level changes.
            old_value: Optional previous value (serialized as string).
            new_value: Optional new value (serialized as string).
            reason: Optional Reason_For_Change (required for post-submission edits).
            actor_id: Actor UUID; defaults to request context actor.
            actor_email: Actor email for denormalized retention.
            request_id: Request identifier; defaults to request context value.
            ip_address: Client IP address.
            user_agent: Client user-agent string.

        Returns:
            The created AuditEvent instance (already added to the session).
        """
        # Auto-populate from request context if not explicitly provided
        if actor_id is None:
            actor_id = get_actor()

        resolved_request_id: str | None = request_id
        if resolved_request_id is None:
            resolved_request_id = get_request_id()

        # Convert string request_id to a UUID object for the Uuid column type.
        # The middleware stores request_id as str(uuid4()). The audit_events
        # table column is Uuid, which requires a UUID object for databases
        # like SQLite. PostgreSQL handles string-to-UUID coercion natively.
        request_id_value: UUID | str | None = resolved_request_id
        if isinstance(resolved_request_id, str):
            try:
                request_id_value = UUID(resolved_request_id)
            except ValueError:
                # Non-UUID string (e.g., in unit tests with mocks); pass through
                request_id_value = resolved_request_id
        if request_id_value is None:
            request_id_value = uuid_mod.uuid4()

        event = AuditEvent(
            actor_id=actor_id,
            actor_email=actor_email,
            timestamp=utc_now(),
            entity_type=entity_type,
            entity_id=entity_id,
            module=module.value if isinstance(module, Module) else str(module),
            actor_kind=actor_kind,
            worker_id=worker_id,
            correlation_id=correlation_id,
            scope_json={
                key: (str(value) if isinstance(value, UUID) else value)
                for key, value in (scope or {}).items()
                if value is not None
            } or None,
            changed_fields=list(changed_fields) if changed_fields is not None else None,
            source_module=(
                source_module.value
                if isinstance(source_module, Module)
                else str(source_module) if source_module is not None else None
            ),
            target_module=(
                target_module.value
                if isinstance(target_module, Module)
                else str(target_module) if target_module is not None else None
            ),
            source_record_id=source_record_id,
            target_record_id=target_record_id,
            action=action,
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            request_id=request_id_value,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        session.add(event)
        # Flush to assign the id immediately (useful for callers that need it),
        # but do NOT commit — the caller's transaction boundary handles that.
        await session.flush()

        logger.info(
            "Audit event recorded: action=%s entity=%s:%s actor=%s request=%s",
            action,
            entity_type,
            entity_id,
            actor_id,
            resolved_request_id,
        )

        return event

    async def search(
        self,
        session: AsyncSession,
        *,
        filters: AuditSearchFilters,
        pagination: PaginationParams | None = None,
    ) -> Any:
        """Search audit events with optional filters and pagination.

        Filterable by actor, entity, study, site, subject, field, date range,
        action, and request_id. Results are ordered by timestamp descending
        (most recent first).

        Args:
            session: The active async session.
            filters: An AuditSearchFilters instance with optional filter values.
            pagination: Optional pagination params; defaults to page 1, size 25.

        Returns:
            A PaginatedResponse containing matching AuditEvent instances.
        """
        query = select(AuditEvent)

        # Apply filters
        if filters.actor_id is not None:
            query = query.where(AuditEvent.actor_id == filters.actor_id)
        if filters.entity_type is not None:
            query = query.where(AuditEvent.entity_type == filters.entity_type)
        if filters.entity_id is not None:
            query = query.where(AuditEvent.entity_id == filters.entity_id)
        if filters.study_id is not None:
            query = query.where(AuditEvent.study_id == filters.study_id)
        if filters.site_id is not None:
            query = query.where(AuditEvent.site_id == filters.site_id)
        if filters.subject_id is not None:
            query = query.where(AuditEvent.subject_id == filters.subject_id)
        if filters.field_name is not None:
            query = query.where(AuditEvent.field_name == filters.field_name)
        if filters.action is not None:
            query = query.where(AuditEvent.action == filters.action)
        if filters.module is not None:
            query = query.where(AuditEvent.module == filters.module)
        if filters.correlation_id is not None:
            query = query.where(AuditEvent.correlation_id == filters.correlation_id)
        if filters.request_id is not None:
            query = query.where(AuditEvent.request_id == filters.request_id)
        if filters.date_from is not None:
            query = query.where(AuditEvent.timestamp >= filters.date_from)
        if filters.date_to is not None:
            query = query.where(AuditEvent.timestamp <= filters.date_to)

        # Order by most recent first
        query = query.order_by(AuditEvent.timestamp.desc())

        # Apply pagination
        if pagination is None:
            pagination = PaginationParams(page=1, page_size=25)

        return await paginate(session, query, pagination)

    async def export(
        self,
        session: AsyncSession,
        *,
        filters: AuditSearchFilters,
    ) -> list[dict]:
        """Export audit events matching filters as flat dictionaries.

        Unlike search(), this method returns ALL matching events (no pagination)
        as dictionaries suitable for CSV/Excel/JSON export.

        Args:
            session: The active async session.
            filters: An AuditSearchFilters instance with optional filter values.

        Returns:
            A list of dictionaries representing the matching audit events.
        """
        query = select(AuditEvent)

        # Apply the same filters as search
        if filters.actor_id is not None:
            query = query.where(AuditEvent.actor_id == filters.actor_id)
        if filters.entity_type is not None:
            query = query.where(AuditEvent.entity_type == filters.entity_type)
        if filters.entity_id is not None:
            query = query.where(AuditEvent.entity_id == filters.entity_id)
        if filters.study_id is not None:
            query = query.where(AuditEvent.study_id == filters.study_id)
        if filters.site_id is not None:
            query = query.where(AuditEvent.site_id == filters.site_id)
        if filters.subject_id is not None:
            query = query.where(AuditEvent.subject_id == filters.subject_id)
        if filters.field_name is not None:
            query = query.where(AuditEvent.field_name == filters.field_name)
        if filters.action is not None:
            query = query.where(AuditEvent.action == filters.action)
        if filters.module is not None:
            query = query.where(AuditEvent.module == filters.module)
        if filters.correlation_id is not None:
            query = query.where(AuditEvent.correlation_id == filters.correlation_id)
        if filters.request_id is not None:
            query = query.where(AuditEvent.request_id == filters.request_id)
        if filters.date_from is not None:
            query = query.where(AuditEvent.timestamp >= filters.date_from)
        if filters.date_to is not None:
            query = query.where(AuditEvent.timestamp <= filters.date_to)

        # Order by timestamp ascending for export (chronological)
        query = query.order_by(AuditEvent.timestamp.asc())

        result = await session.execute(query)
        events = result.scalars().all()

        export_rows: list[dict] = []
        for event in events:
            export_rows.append(
                AuditEventExport(
                    id=str(event.id),
                    actor_id=str(event.actor_id) if event.actor_id else None,
                    actor_email=event.actor_email,
                    timestamp=event.timestamp.isoformat(),
                    entity_type=event.entity_type,
                    entity_id=str(event.entity_id),
                    module=event.module if isinstance(event.module, str) else "EDC",
                    actor_kind=event.actor_kind if isinstance(event.actor_kind, str) else "user",
                    worker_id=event.worker_id if isinstance(event.worker_id, str) else None,
                    correlation_id=(
                        event.correlation_id
                        if isinstance(event.correlation_id, str)
                        else None
                    ),
                    scope_json=event.scope_json if isinstance(event.scope_json, dict) else None,
                    changed_fields=(
                        event.changed_fields if isinstance(event.changed_fields, list) else None
                    ),
                    study_id=str(event.study_id) if event.study_id else None,
                    site_id=str(event.site_id) if event.site_id else None,
                    subject_id=str(event.subject_id) if event.subject_id else None,
                    action=event.action,
                    field_name=event.field_name,
                    old_value=event.old_value,
                    new_value=event.new_value,
                    reason=event.reason,
                    request_id=str(event.request_id),
                    ip_address=event.ip_address,
                    user_agent=event.user_agent,
                ).model_dump()
            )

        return export_rows


# Module-level singleton for convenience. Services import and use this instance.
audit_service = AuditService()
