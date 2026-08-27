"""Query routes — query lifecycle management and threaded message history.

Satisfies Requirements:
  - 13.1: Query linked to exactly one affected object (target_type + target_id).
  - 13.3: Respond transitions Open/Reopened → Answered and appends to message thread.
  - 13.4: Close transitions Open/Answered → Closed with closing actor/timestamp.
  - 13.5: Reopen transitions Closed → Reopened.
  - 21.1: All endpoints mounted under /api/v1.
  - 21.2: List endpoints return a pagination envelope.

Endpoints:
  - GET    /studies/{study_id}/queries             list queries (query.create or form.read)
  - POST   /studies/{study_id}/queries             create query (query.create)
  - GET    /queries/{query_id}                     get query with messages (form.read)
  - POST   /queries/{query_id}/respond             respond to query (query.respond)
  - POST   /queries/{query_id}/close               close query (query.close)
  - POST   /queries/{query_id}/reopen              reopen query (query.reopen)
  - POST   /queries/{query_id}/cancel              cancel query (query.cancel)
  - GET    /queries/{query_id}/history             get threaded message history (form.read)
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.models.identity import User
from app.models.query import QueryStatus, QueryTargetType, QueryType
from app.schemas.base import PaginatedResponse
from app.schemas.query import (
    QueryCreate,
    QueryListResponse,
    QueryMessageResponse,
    QueryRespond,
    QueryResponse,
)
from app.services.query_service import query_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study-scoped query collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_queries_router = APIRouter(prefix="/studies", tags=["queries"])


@study_queries_router.get(
    "/{study_id}/queries", response_model=PaginatedResponse[QueryListResponse]
)
async def list_queries(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
    pagination: Annotated[PaginationParams, Depends()],
    status: QueryStatus | None = None,
    target_type: QueryTargetType | None = None,
    query_type: QueryType | None = None,
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
) -> PaginatedResponse[QueryListResponse]:
    """List queries for a study (paginated, filterable by status/target_type).

    Permission: form.read
    Requirement 21.2: Paginated response envelope.
    """
    from app.schemas.query import QueryFilters

    filters = QueryFilters(
        status=status,
        target_type=target_type,
        query_type=query_type,
        site_id=site_id,
        subject_id=subject_id,
    )

    result = await query_service.list_queries(
        session, study_id, filters=filters, pagination=pagination
    )
    return PaginatedResponse[QueryListResponse](
        items=[QueryListResponse.model_validate(q) for q in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_queries_router.post(
    "/{study_id}/queries", response_model=QueryResponse, status_code=201
)
async def create_query(
    study_id: UUID,
    body: QueryCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("query.create"))],
) -> QueryResponse:
    """Create a new query linked to an affected object within a study.

    Permission: query.create
    Requirement 13.1: Query linked to exactly one affected object.
    """
    query = await query_service.create_query(
        session=session,
        study_id=study_id,
        target_type=body.target_type,
        target_id=body.target_id,
        text=body.text,
        actor_id=current_user.id,
        site_id=body.site_id,
        subject_id=body.subject_id,
        query_type=body.query_type,
    )
    return QueryResponse.model_validate(query)


# ---------------------------------------------------------------------------
# Single-query operations (mounted at /queries)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/queries", tags=["queries"])


@router.get("/{query_id}", response_model=QueryResponse)
async def get_query(
    query_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
) -> QueryResponse:
    """Get a query by ID, including its threaded messages.

    Permission: form.read
    """
    query = await query_service.get_query(session, query_id)
    return QueryResponse.model_validate(query)


@router.post("/{query_id}/respond", response_model=QueryResponse)
async def respond_to_query(
    query_id: UUID,
    body: QueryRespond,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("query.respond"))],
) -> QueryResponse:
    """Respond to a query — transitions Open/Reopened → Answered.

    Permission: query.respond
    Requirement 13.3: Respond appends to message thread and transitions status.
    """
    query = await query_service.get_query(session, query_id)
    updated = await query_service.respond(
        session=session,
        query=query,
        message=body.message,
        actor_id=current_user.id,
    )
    return QueryResponse.model_validate(updated)


@router.post("/{query_id}/close", response_model=QueryResponse)
async def close_query(
    query_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("query.close"))],
) -> QueryResponse:
    """Close a query — transitions Open/Answered/Reopened → Closed.

    Permission: query.close
    Requirement 13.4: Close records the closing actor and timestamp.
    """
    query = await query_service.get_query(session, query_id)
    updated = await query_service.close(
        session=session,
        query=query,
        actor_id=current_user.id,
    )
    return QueryResponse.model_validate(updated)


@router.post("/{query_id}/reopen", response_model=QueryResponse)
async def reopen_query(
    query_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("query.reopen"))],
) -> QueryResponse:
    """Reopen a closed query — transitions Closed → Reopened.

    Permission: query.reopen
    Requirement 13.5: Reopen transitions Closed → Reopened.
    """
    query = await query_service.get_query(session, query_id)
    updated = await query_service.reopen(
        session=session,
        query=query,
        actor_id=current_user.id,
    )
    return QueryResponse.model_validate(updated)


@router.post("/{query_id}/cancel", response_model=QueryResponse)
async def cancel_query(
    query_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("query.cancel"))],
) -> QueryResponse:
    """Cancel a query — transitions Open/Answered → Cancelled.

    Permission: query.cancel
    """
    query = await query_service.get_query(session, query_id)
    updated = await query_service.cancel(
        session=session,
        query=query,
        actor_id=current_user.id,
    )
    return QueryResponse.model_validate(updated)


@router.get("/{query_id}/history", response_model=list[QueryMessageResponse])
async def get_query_history(
    query_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
) -> list[QueryMessageResponse]:
    """Get the threaded message history for a query.

    Permission: form.read
    Requirement 13.6: Complete threaded message history preserved.
    """
    query = await query_service.get_query(session, query_id)
    return [QueryMessageResponse.model_validate(m) for m in query.messages]
