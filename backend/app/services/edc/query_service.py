"""Query_Service — query lifecycle and threaded message management.

Satisfies Requirements:
  - 13.1: Query linked to exactly one affected object (target_type + target_id).
  - 13.2: Query statuses Open, Answered, Closed, Reopened, Cancelled.
  - 13.3: Respond transitions Open/Reopened → Answered and appends to message thread.
  - 13.4: Close transitions Open/Answered → Closed with closing actor/timestamp.
  - 13.5: Reopen transitions Closed → Reopened.
  - 13.6: Complete threaded message history preserved.
  - 13.7: Every query action writes an Audit_Event.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.designer.form_metadata import FieldDefinition, FormSection
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.form_record import FormRecord
from app.models.edc.query import Query, QueryMessage, QueryStatus, QueryTargetType, QueryType
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
    UserStatus,
)
from app.schemas.edc.query import QueryFilters
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.lock_service import lock_service
from app.services.shared.notification_service import notification_service

logger = logging.getLogger(__name__)

# Valid status transitions per action
_RESPOND_FROM = {QueryStatus.open, QueryStatus.reopened}
_CLOSE_FROM = {QueryStatus.open, QueryStatus.answered, QueryStatus.reopened}
_REOPEN_FROM = {QueryStatus.closed}
_CANCEL_FROM = {QueryStatus.open, QueryStatus.answered}


class QueryService:
    """Manages query creation, lifecycle transitions, and threaded history."""

    # ------------------------------------------------------------------
    # Create (Req 13.1, 13.7)
    # ------------------------------------------------------------------

    async def create_query(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        target_type: str,
        target_id: UUID,
        text: str,
        actor_id: UUID,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        query_type: str = QueryType.manual,
        assigned_role: str | None = None,
        design_version_id: UUID | None = None,
    ) -> Query:
        """Create a new Query with status Open, linked to exactly one affected object.

        Args:
            session: Active async database session (caller's transaction).
            study_id: UUID of the parent study.
            target_type: One of Subject, Visit_Instance, Form_Instance,
                         Form_Record, or Field.
            target_id: UUID of the affected object.
            text: Initial query description text.
            actor_id: UUID of the user creating the query.
            site_id: Optional site context.
            subject_id: Optional subject context.
            query_type: Origin of the query (manual or system).
            assigned_role: Optional role whose in-scope users are notified.
            design_version_id: Published design version binding (R2.7/7.3/11.2).
                When omitted it is resolved from the owning subject's bound
                ``study_version_id``.

        Returns:
            The created Query instance with status Open.
        """
        (
            target_study_id,
            target_site_id,
            target_subject_id,
            target_design_version_id,
        ) = await self._resolve_target_context(session, target_type, target_id)
        if target_study_id != study_id:
            raise ValidationError(
                message="Query target does not belong to the requested study",
                details={"target_type": str(target_type), "target_id": str(target_id)},
            )
        if site_id is not None and site_id != target_site_id:
            raise ValidationError(
                message="Query site context does not match its target", details={}
            )
        if subject_id is not None and subject_id != target_subject_id:
            raise ValidationError(
                message="Query subject context does not match its target", details={}
            )
        site_id = target_site_id
        subject_id = target_subject_id
        design_version_id = design_version_id or target_design_version_id
        await self._ensure_not_hard_locked(session, subject_id)

        query = Query(
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            target_type=target_type,
            target_id=target_id,
            text=text,
            query_type=query_type,
            assigned_role=assigned_role,
            status=QueryStatus.open,
            created_by=actor_id,
            design_version_id=design_version_id,
            messages=[],
        )
        session.add(query)
        await session.flush()

        # Write Audit_Event (Req 13.7)
        await audit_service.record(
            session,
            entity_type="query",
            entity_id=query.id,
            action="create",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            new_value=f"target_type={target_type}, target_id={target_id}, status=Open",
        )

        await notification_service.on_query_assigned(session, query)

        logger.info(
            "Query created: id=%s study_id=%s target=%s:%s actor=%s",
            query.id,
            study_id,
            target_type,
            target_id,
            actor_id,
        )
        return query

    async def _resolve_target_context(
        self,
        session: AsyncSession,
        target_type: str,
        target_id: UUID,
    ) -> tuple[UUID, UUID, UUID, UUID]:
        """Resolve authoritative query scope from the affected clinical object."""
        normalized = QueryTargetType(target_type)
        subject: Subject | None = None
        if normalized == QueryTargetType.subject:
            subject = await session.get(Subject, target_id)
        elif normalized == QueryTargetType.visit_instance:
            visit = await session.get(VisitInstance, target_id)
            subject = visit.subject if visit else None
        elif normalized == QueryTargetType.form_instance:
            form = await session.get(FormInstance, target_id)
            subject = form.subject if form else None
        elif normalized == QueryTargetType.form_record:
            record = await session.get(FormRecord, target_id)
            subject = record.form_instance.subject if record else None
        elif normalized == QueryTargetType.field:
            field = await session.get(FieldValue, target_id)
            subject = field.form_instance.subject if field else None
        if subject is None or subject.deleted_at is not None:
            raise NotFoundError(message="Query target not found", details={})
        return (
            subject.study_id,
            subject.site_id,
            subject.id,
            subject.study_version_id,
        )

    async def _resolve_design_version_id(
        self, session: AsyncSession, subject_id: UUID | None
    ) -> UUID | None:
        """Resolve the published-design binding from the owning subject.

        Every query belongs to a subject-scoped object, so the binding is the
        subject's bound ``study_version_id`` (R2.7/7.3/11.2). Returns None when
        no subject context is available so the caller surfaces the constraint.
        """
        if subject_id is None:
            return None
        result = await session.execute(
            select(Subject.study_version_id).where(Subject.id == subject_id)
        )
        return result.scalar_one_or_none()

    async def list_assignment_roles(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID,
    ) -> list[str]:
        """Return active recipient roles available in the target's scope."""
        scope_filter = or_(
            and_(
                Role.scope_level == ScopeLevel.system,
                UserRole.study_id.is_(None),
                UserRole.site_id.is_(None),
            ),
            and_(
                Role.scope_level == ScopeLevel.study,
                UserRole.study_id == study_id,
                UserRole.site_id.is_(None),
            ),
            and_(
                Role.scope_level == ScopeLevel.site,
                UserRole.study_id == study_id,
                UserRole.site_id == site_id,
            ),
        )
        result = await session.execute(
            select(Role.name)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(User, User.id == UserRole.user_id)
            .where(
                Permission.code == "query.respond",
                User.status == UserStatus.active,
                scope_filter,
            )
            .distinct()
            .order_by(Role.name)
        )
        return list(result.scalars().all())

    async def ensure_field_target(
        self,
        session: AsyncSession,
        *,
        form_instance: FormInstance,
        field_definition_id: UUID,
    ) -> FieldValue:
        """Return a field-value target, creating an empty placeholder if unanswered."""
        await self._ensure_not_hard_locked(session, form_instance.subject_id)

        # Serialize concurrent first-query attempts for fields in the same form.
        await session.execute(
            select(FormInstance.id).where(FormInstance.id == form_instance.id).with_for_update()
        )
        definition_result = await session.execute(
            select(FieldDefinition.id)
            .join(FormSection, FormSection.id == FieldDefinition.form_section_id)
            .where(
                FieldDefinition.id == field_definition_id,
                FormSection.form_definition_id == form_instance.form_definition_id,
            )
        )
        if definition_result.scalar_one_or_none() is None:
            raise NotFoundError(message="Query field not found in form instance", details={})

        value_result = await session.execute(
            select(FieldValue).where(
                FieldValue.form_instance_id == form_instance.id,
                FieldValue.field_definition_id == field_definition_id,
            )
        )
        field_value = value_result.scalars().first()
        if field_value is None:
            field_value = FieldValue(
                form_instance=form_instance,
                field_definition_id=field_definition_id,
                value=None,
                design_version_id=form_instance.design_version_id,
            )
            session.add(field_value)
            await session.flush()
        return field_value

    async def list_field_queries(
        self,
        session: AsyncSession,
        *,
        form_instance: FormInstance,
        field_definition_id: UUID,
        pagination: PaginationParams,
    ) -> PaginatedResponse:
        """List every query linked to a field in one form instance."""
        definition_result = await session.execute(
            select(FieldDefinition.id)
            .join(FormSection, FormSection.id == FieldDefinition.form_section_id)
            .where(
                FieldDefinition.id == field_definition_id,
                FormSection.form_definition_id == form_instance.form_definition_id,
            )
        )
        if definition_result.scalar_one_or_none() is None:
            raise NotFoundError(message="Query field not found in form instance", details={})

        target_result = await session.execute(
            select(FieldValue.id).where(
                FieldValue.form_instance_id == form_instance.id,
                FieldValue.field_definition_id == field_definition_id,
            )
        )
        target_ids = list(target_result.scalars().all())
        statement = select(Query).where(
            Query.study_id == form_instance.subject.study_id,
            Query.target_type == QueryTargetType.field,
            Query.target_id.in_(target_ids),
        )
        return await paginate(session, statement.order_by(Query.created_at.desc()), pagination)

    # ------------------------------------------------------------------
    # Respond (Req 13.3, 13.6, 13.7)
    # ------------------------------------------------------------------

    async def respond(
        self,
        session: AsyncSession,
        query: Query,
        message: str,
        actor_id: UUID,
    ) -> Query:
        """Respond to a Query — transitions Open/Reopened → Answered.

        Appends a QueryMessage to the threaded history.

        Args:
            session: Active async database session.
            query: The Query instance to respond to.
            message: The response message text.
            actor_id: UUID of the user responding.

        Returns:
            The updated Query instance with status Answered.

        Raises:
            BusinessRuleError: If the query is not in Open or Reopened status.
        """
        await self._ensure_not_hard_locked(session, query.subject_id)
        if query.status not in _RESPOND_FROM:
            raise BusinessRuleError(
                message=f"Cannot respond to a query in status '{query.status}'",
                details={
                    "query_id": str(query.id),
                    "current_status": str(query.status),
                    "allowed_statuses": [s.value for s in _RESPOND_FROM],
                },
            )

        old_status = query.status

        # Append message to thread (Req 13.6)
        query_message = QueryMessage(
            query_id=query.id,
            author_id=actor_id,
            message=message,
        )
        session.add(query_message)

        # Transition status (Req 13.3)
        query.status = QueryStatus.answered
        query.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 13.7)
        await audit_service.record(
            session,
            entity_type="query",
            entity_id=query.id,
            action="respond",
            study_id=query.study_id,
            site_id=query.site_id,
            subject_id=query.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=str(old_status),
            new_value=str(QueryStatus.answered),
        )

        logger.info(
            "Query responded: id=%s %s -> Answered actor=%s",
            query.id,
            old_status,
            actor_id,
        )
        return query

    # ------------------------------------------------------------------
    # Close (Req 13.4, 13.7)
    # ------------------------------------------------------------------

    async def close(
        self,
        session: AsyncSession,
        query: Query,
        actor_id: UUID,
    ) -> Query:
        """Close a Query — transitions Open/Answered → Closed.

        Records the closing actor and timestamp.

        Args:
            session: Active async database session.
            query: The Query instance to close.
            actor_id: UUID of the user closing the query.

        Returns:
            The updated Query instance with status Closed.

        Raises:
            BusinessRuleError: If the query is not in Open or Answered status.
        """
        await self._ensure_not_hard_locked(session, query.subject_id)
        if query.status not in _CLOSE_FROM:
            raise BusinessRuleError(
                message=f"Cannot close a query in status '{query.status}'",
                details={
                    "query_id": str(query.id),
                    "current_status": str(query.status),
                    "allowed_statuses": [s.value for s in _CLOSE_FROM],
                },
            )

        old_status = query.status

        # Transition (Req 13.4)
        query.status = QueryStatus.closed
        query.closed_at = datetime.now(UTC)
        query.closed_by = actor_id
        query.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 13.7)
        await audit_service.record(
            session,
            entity_type="query",
            entity_id=query.id,
            action="close",
            study_id=query.study_id,
            site_id=query.site_id,
            subject_id=query.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=str(old_status),
            new_value=str(QueryStatus.closed),
        )

        logger.info(
            "Query closed: id=%s %s -> Closed actor=%s",
            query.id,
            old_status,
            actor_id,
        )
        return query

    # ------------------------------------------------------------------
    # Reopen (Req 13.5, 13.7)
    # ------------------------------------------------------------------

    async def reopen(
        self,
        session: AsyncSession,
        query: Query,
        actor_id: UUID,
    ) -> Query:
        """Reopen a Closed Query — transitions Closed → Reopened.

        Args:
            session: Active async database session.
            query: The Query instance to reopen.
            actor_id: UUID of the user reopening the query.

        Returns:
            The updated Query instance with status Reopened.

        Raises:
            BusinessRuleError: If the query is not in Closed status.
        """
        await self._ensure_not_hard_locked(session, query.subject_id)
        if query.status not in _REOPEN_FROM:
            raise BusinessRuleError(
                message=f"Cannot reopen a query in status '{query.status}'",
                details={
                    "query_id": str(query.id),
                    "current_status": str(query.status),
                    "allowed_statuses": [s.value for s in _REOPEN_FROM],
                },
            )

        old_status = query.status

        # Transition (Req 13.5)
        query.status = QueryStatus.reopened
        query.closed_at = None
        query.closed_by = None
        query.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 13.7)
        await audit_service.record(
            session,
            entity_type="query",
            entity_id=query.id,
            action="reopen",
            study_id=query.study_id,
            site_id=query.site_id,
            subject_id=query.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=str(old_status),
            new_value=str(QueryStatus.reopened),
        )

        logger.info(
            "Query reopened: id=%s Closed -> Reopened actor=%s",
            query.id,
            actor_id,
        )
        return query

    # ------------------------------------------------------------------
    # Cancel (Req 13.7)
    # ------------------------------------------------------------------

    async def cancel(
        self,
        session: AsyncSession,
        query: Query,
        actor_id: UUID,
    ) -> Query:
        """Cancel a Query — transitions Open/Answered → Cancelled.

        Args:
            session: Active async database session.
            query: The Query instance to cancel.
            actor_id: UUID of the user cancelling the query.

        Returns:
            The updated Query instance with status Cancelled.

        Raises:
            BusinessRuleError: If the query is not in Open or Answered status.
        """
        await self._ensure_not_hard_locked(session, query.subject_id)
        if query.status not in _CANCEL_FROM:
            raise BusinessRuleError(
                message=f"Cannot cancel a query in status '{query.status}'",
                details={
                    "query_id": str(query.id),
                    "current_status": str(query.status),
                    "allowed_statuses": [s.value for s in _CANCEL_FROM],
                },
            )

        old_status = query.status

        # Transition
        query.status = QueryStatus.cancelled
        query.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 13.7)
        await audit_service.record(
            session,
            entity_type="query",
            entity_id=query.id,
            action="cancel",
            study_id=query.study_id,
            site_id=query.site_id,
            subject_id=query.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=str(old_status),
            new_value=str(QueryStatus.cancelled),
        )

        logger.info(
            "Query cancelled: id=%s %s -> Cancelled actor=%s",
            query.id,
            old_status,
            actor_id,
        )
        return query

    @staticmethod
    async def _ensure_not_hard_locked(session: AsyncSession, subject_id: UUID | None) -> None:
        if subject_id is None:
            return
        if await lock_service.is_hard_locked(
            session,
            object_type="subject",
            object_id=subject_id,
        ):
            raise BusinessRuleError(
                message="Query state cannot be changed while the subject is locked",
                details={},
            )

    # ------------------------------------------------------------------
    # Get by ID (with messages)
    # ------------------------------------------------------------------

    async def get_query(self, session: AsyncSession, query_id: UUID) -> Query:
        """Retrieve a Query by its primary key, including messages.

        Args:
            session: Active async database session.
            query_id: The UUID of the query.

        Returns:
            The Query instance with messages eagerly loaded.

        Raises:
            NotFoundError: If no query exists with the given ID.
        """
        result = await session.execute(select(Query).where(Query.id == query_id))
        query = result.scalars().first()
        if query is None:
            raise NotFoundError(
                message="Query not found",
                details={"query_id": str(query_id)},
            )
        return query

    # ------------------------------------------------------------------
    # List (with filters and pagination)
    # ------------------------------------------------------------------

    async def list_queries(
        self,
        session: AsyncSession,
        study_id: UUID,
        filters: QueryFilters | None = None,
        pagination: PaginationParams | None = None,
        authorized_site_ids: set[UUID] | None = None,
    ) -> PaginatedResponse:
        """List queries for a study with optional filters and pagination.

        Args:
            session: Active async database session.
            study_id: UUID of the parent study.
            filters: Optional QueryFilters with status/target_type/query_type/site/subject.
            pagination: Page/page_size pagination parameters.

        Returns:
            PaginatedResponse containing Query instances (without messages).
        """
        stmt = select(Query).where(Query.study_id == study_id).order_by(Query.created_at.desc())
        if authorized_site_ids is not None:
            stmt = stmt.where(Query.site_id.in_(authorized_site_ids))

        # Apply optional filters
        if filters is not None:
            if filters.status is not None:
                stmt = stmt.where(Query.status == filters.status)
            if filters.target_type is not None:
                stmt = stmt.where(Query.target_type == filters.target_type)
            if filters.query_type is not None:
                stmt = stmt.where(Query.query_type == filters.query_type)
            if filters.site_id is not None:
                stmt = stmt.where(Query.site_id == filters.site_id)
            if filters.subject_id is not None:
                stmt = stmt.where(Query.subject_id == filters.subject_id)
            if filters.assigned_role is not None:
                stmt = stmt.where(Query.assigned_role == filters.assigned_role)
            if filters.active is True:
                stmt = stmt.where(
                    Query.status.in_((QueryStatus.open, QueryStatus.answered, QueryStatus.reopened))
                )
            elif filters.active is False:
                stmt = stmt.where(Query.status.in_((QueryStatus.closed, QueryStatus.cancelled)))

        if pagination is None:
            pagination = PaginationParams(page=1, page_size=25)

        return await paginate(session, stmt, pagination)

    async def history(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams,
        *,
        authorized_site_ids: set[UUID] | None = None,
        subject_id: UUID | None = None,
    ) -> PaginatedResponse:
        """Return immutable query audit events for an authorized study scope."""
        stmt = select(AuditEvent).where(
            AuditEvent.study_id == study_id,
            AuditEvent.entity_type == "query",
        )
        if authorized_site_ids is not None:
            stmt = stmt.where(AuditEvent.site_id.in_(authorized_site_ids))
        if subject_id is not None:
            stmt = stmt.where(AuditEvent.subject_id == subject_id)
        return await paginate(session, stmt.order_by(AuditEvent.timestamp.desc()), pagination)


# Module-level singleton for convenience
query_service = QueryService()
