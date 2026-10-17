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
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_user, get_db, get_permission_service
from app.models.edc.query import QueryStatus, QueryTargetType, QueryType
from app.models.shared.identity import User
from app.schemas.edc.query import (
    FieldQueryCreate,
    QueryCreate,
    QueryListResponse,
    QueryMessageResponse,
    QueryRespond,
    QueryResponse,
)
from app.schemas.shared.audit import AuditEventResponse
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.query_service import query_service
from app.services.edc.scope_service import edc_scope_service
from app.services.shared.permission_service import PermissionService

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study-scoped query collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_queries_router = APIRouter(prefix="/studies", tags=["queries"])


@study_queries_router.get(
    "/{study_id}/queries/assignment-roles",
    response_model=list[str],
)
async def list_query_assignment_roles(
    study_id: UUID,
    target_type: QueryTargetType,
    target_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> list[str]:
    """List roles with active recipients in the query target's scope."""
    target_study_id, target_site_id, _, _ = await query_service._resolve_target_context(
        session, target_type, target_id
    )
    if target_study_id != study_id:
        from app.core.exceptions import ValidationError

        raise ValidationError(
            message="Query target does not belong to the requested study", details={}
        )
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "query.create",
        study_id=target_study_id,
        site_id=target_site_id,
    )
    return await query_service.list_assignment_roles(
        session,
        study_id=target_study_id,
        site_id=target_site_id,
    )


@study_queries_router.get(
    "/{study_id}/queries", response_model=PaginatedResponse[QueryListResponse]
)
async def list_queries(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[PaginationParams, Depends()],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    status: QueryStatus | None = None,
    target_type: QueryTargetType | None = None,
    query_type: QueryType | None = None,
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
    assigned_role: str | None = None,
    active: bool | None = None,
) -> PaginatedResponse[QueryListResponse]:
    """List queries for a study (paginated, filterable by status/target_type).

    Permission: form.read
    Requirement 21.2: Paginated response envelope.
    """
    from app.schemas.edc.query import QueryFilters

    filters = QueryFilters(
        status=status,
        target_type=target_type,
        query_type=query_type,
        site_id=site_id,
        subject_id=subject_id,
        assigned_role=assigned_role,
        active=active,
    )

    authorized_site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, "form.read", study_id
    )
    result = await query_service.list_queries(
        session,
        study_id,
        filters=filters,
        pagination=pagination,
        authorized_site_ids=authorized_site_ids,
    )
    return PaginatedResponse[QueryListResponse](
        items=[
            QueryListResponse.model_validate(
                {
                    **QueryListResponse.model_validate(q).model_dump(),
                    "site_label": (f"{q.site.site_number} — {q.site.name}" if q.site else None),
                    "subject_label": q.subject.subject_number if q.subject else None,
                    "age_days": max((datetime.now(UTC) - q.created_at).days, 0),
                }
            )
            for q in result.items
        ],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_queries_router.get(
    "/{study_id}/queries/history",
    response_model=PaginatedResponse[AuditEventResponse],
)
async def list_query_history(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[PaginationParams, Depends()],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    subject_id: UUID | None = None,
) -> PaginatedResponse[AuditEventResponse]:
    authorized_site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, "form.read", study_id
    )
    result = await query_service.history(
        session,
        study_id,
        pagination,
        authorized_site_ids=authorized_site_ids,
        subject_id=subject_id,
    )
    return PaginatedResponse[AuditEventResponse](
        items=[AuditEventResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_queries_router.post("/{study_id}/queries", response_model=QueryResponse, status_code=201)
async def create_query(
    study_id: UUID,
    body: QueryCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Create a new query linked to an affected object within a study.

    Permission: query.create
    Requirement 13.1: Query linked to exactly one affected object.
    """
    target_study_id, target_site_id, _, _ = await query_service._resolve_target_context(
        session, body.target_type, body.target_id
    )
    if target_study_id != study_id:
        from app.core.exceptions import ValidationError

        raise ValidationError(
            message="Query target does not belong to the requested study", details={}
        )
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "query.create",
        study_id=target_study_id,
        site_id=target_site_id,
    )
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
        assigned_role=body.assigned_role,
    )
    return QueryResponse.model_validate(query)


# ---------------------------------------------------------------------------
# Form-field contextual query creation (mounted at /form-instances)
# ---------------------------------------------------------------------------

form_queries_router = APIRouter(prefix="/form-instances", tags=["queries"])


@form_queries_router.get(
    "/{form_instance_id}/fields/{field_definition_id}/queries",
    response_model=PaginatedResponse[QueryListResponse],
)
async def list_field_queries(
    form_instance_id: UUID,
    field_definition_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[PaginationParams, Depends()],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> PaginatedResponse[QueryListResponse]:
    """List current and historical queries for one field on the data-entry form."""
    from app.services.edc.data_capture_service import data_capture_service

    form_instance = await data_capture_service.load(session, form_instance_id)
    edc_scope_service.require_form(
        current_user,
        permission_service,
        "form.read",
        form_instance,
    )
    result = await query_service.list_field_queries(
        session,
        form_instance=form_instance,
        field_definition_id=field_definition_id,
        pagination=pagination,
    )
    return PaginatedResponse[QueryListResponse](
        items=[QueryListResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@form_queries_router.post(
    "/{form_instance_id}/fields/{field_definition_id}/queries",
    response_model=QueryResponse,
    status_code=201,
)
async def create_field_query(
    form_instance_id: UUID,
    field_definition_id: UUID,
    body: FieldQueryCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Create a field-specific query, including when the field is unanswered."""
    from app.services.edc.data_capture_service import data_capture_service

    form_instance = await data_capture_service.load(session, form_instance_id)
    edc_scope_service.require_form(
        current_user,
        permission_service,
        "query.create",
        form_instance,
    )
    field_value = await query_service.ensure_field_target(
        session,
        form_instance=form_instance,
        field_definition_id=field_definition_id,
    )
    query = await query_service.create_query(
        session=session,
        study_id=form_instance.subject.study_id,
        target_type=QueryTargetType.field,
        target_id=field_value.id,
        text=body.text,
        actor_id=current_user.id,
        query_type=QueryType.manual,
        assigned_role=body.assigned_role,
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Get a query by ID, including its threaded messages.

    Permission: form.read
    """
    query = await query_service.get_query(session, query_id)
    edc_scope_service.require_query(current_user, permission_service, "form.read", query)
    return QueryResponse.model_validate(query)


@router.post("/{query_id}/respond", response_model=QueryResponse)
async def respond_to_query(
    query_id: UUID,
    body: QueryRespond,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Respond to a query — transitions Open/Reopened → Answered.

    Permission: query.respond
    Requirement 13.3: Respond appends to message thread and transitions status.
    """
    query = await query_service.get_query(session, query_id)
    edc_scope_service.require_query(current_user, permission_service, "query.respond", query)
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Close a query — transitions Open/Answered/Reopened → Closed.

    Permission: query.close
    Requirement 13.4: Close records the closing actor and timestamp.
    """
    query = await query_service.get_query(session, query_id)
    edc_scope_service.require_query(current_user, permission_service, "query.close", query)
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Reopen a closed query — transitions Closed → Reopened.

    Permission: query.reopen
    Requirement 13.5: Reopen transitions Closed → Reopened.
    """
    query = await query_service.get_query(session, query_id)
    edc_scope_service.require_query(current_user, permission_service, "query.reopen", query)
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> QueryResponse:
    """Cancel a query — transitions Open/Answered → Cancelled.

    Permission: query.cancel
    """
    query = await query_service.get_query(session, query_id)
    edc_scope_service.require_query(current_user, permission_service, "query.cancel", query)
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> list[QueryMessageResponse]:
    """Get the threaded message history for a query.

    Permission: form.read
    Requirement 13.6: Complete threaded message history preserved.
    """
    query = await query_service.get_query(session, query_id)
    edc_scope_service.require_query(current_user, permission_service, "form.read", query)
    return [QueryMessageResponse.model_validate(m) for m in query.messages]
