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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.query import Query, QueryMessage, QueryStatus, QueryType
from app.schemas.base import PaginatedResponse
from app.schemas.query import QueryFilters
from app.services.notification_service import notification_service

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

        Returns:
            The created Query instance with status Open.
        """
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
        result = await session.execute(
            select(Query).where(Query.id == query_id)
        )
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
        stmt = (
            select(Query)
            .where(Query.study_id == study_id)
            .order_by(Query.created_at.desc())
        )

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

        if pagination is None:
            pagination = PaginationParams(page=1, page_size=25)

        return await paginate(session, stmt, pagination)


# Module-level singleton for convenience
query_service = QueryService()
