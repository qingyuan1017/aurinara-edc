"""Users, roles, and permissions routes.

Satisfies Requirements:
  - 3.1: Invite a user with a pending record and single-use token.
  - 3.2: Accept a valid invitation (no auth required).
  - 3.3: Assign roles at study/site scope.
  - 3.4: Deactivate a user (soft), retaining the record.
  - 21.1: All endpoints under /api/v1 with paginated list responses.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.core.exceptions import NotFoundError
from app.core.permissions import PERMISSION_CODES
from app.core.security import hash_password
from app.models.identity import User
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.schemas.base import PaginatedResponse
from app.schemas.user import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationResponse,
    RoleAssignmentRequest,
    RoleCreateRequest,
    RoleResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.user_service import InvitationError, user_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Repository singletons
_user_repo = UserRepository()
_role_repo = RoleRepository()


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    response_model=PaginatedResponse[UserResponse],
    dependencies=[Depends(require_permission("user.list"))],
)
async def list_users(
    session: DbSession,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = Query(default=None, description="Filter by user status"),
    search: str | None = Query(default=None, description="Search by name or email"),
) -> PaginatedResponse[UserResponse]:
    """List users with optional filters and pagination.

    Requirement 3.3, 21.1: Paginated user listing.
    """
    return await _user_repo.list_users(
        session,
        status=status,
        search=search,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=201,
)
async def create_user(
    body: UserCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("user.create"))],
) -> UserResponse:
    """Create a new user account.

    Requirement 3.1: Create user with pending status.
    """
    password_hash_value = hash_password(body.password)
    user = await _user_repo.create(session, body, password_hash=password_hash_value)

    await audit_service.record(
        session,
        entity_type="user",
        entity_id=user.id,
        action="create",
        actor_id=current_user.id,
        new_value=body.email,
    )

    return UserResponse.model_validate(user)


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission("user.list"))],
)
async def get_user(user_id: UUID, session: DbSession) -> UserResponse:
    """Get a single user by ID.

    Requirement 3.3: User read access.
    """
    user = await _user_repo.get_by_id(session, user_id)
    if user is None:
        raise NotFoundError(message="User not found", details={"user_id": str(user_id)})
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("user.update"))],
) -> UserResponse:
    """Update an existing user's profile.

    Requirement 3.3: User update with audit trail.
    """
    user = await _user_repo.get_by_id(session, user_id)
    if user is None:
        raise NotFoundError(message="User not found", details={"user_id": str(user_id)})

    old_values = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": user.status,
    }

    user = await _user_repo.update(session, user, body)

    await audit_service.record(
        session,
        entity_type="user",
        entity_id=user.id,
        action="update",
        actor_id=current_user.id,
        old_value=str(old_values),
        new_value=str(body.model_dump(exclude_unset=True)),
    )

    return UserResponse.model_validate(user)


@router.post(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
)
async def deactivate_user(
    user_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("user.deactivate"))],
) -> UserResponse:
    """Deactivate a user account (soft-delete).

    Requirement 3.4: Soft-deactivate, revoke sessions, retain record.
    """
    user = await user_service.deactivate(
        session=session, user_id=user_id, actor_id=current_user.id
    )
    return UserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# Role endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/roles",
    response_model=PaginatedResponse[RoleResponse],
    dependencies=[Depends(require_permission("role.list"))],
)
async def list_roles(
    session: DbSession,
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[RoleResponse]:
    """List all roles with pagination.

    Requirement 3.3: Role listing for assignment.
    """
    return await _role_repo.list_roles(
        session, page=pagination.page, page_size=pagination.page_size
    )


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=201,
)
async def create_role(
    body: RoleCreateRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("role.create"))],
) -> RoleResponse:
    """Create a new role.

    Requirement 3.3: Role management.
    """
    role = await _role_repo.create(
        session,
        name=body.name,
        scope_level=body.scope_level,
        description=body.description,
    )

    await audit_service.record(
        session,
        entity_type="role",
        entity_id=role.id,
        action="create",
        actor_id=current_user.id,
        new_value=body.name,
    )

    return RoleResponse.model_validate(role)


# ---------------------------------------------------------------------------
# Permission endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/permissions",
    response_model=list[str],
    dependencies=[Depends(require_permission("role.list"))],
)
async def list_permissions() -> list[str]:
    """List all available permission codes.

    Requirement 3.3: Permission code enumeration for role configuration.
    """
    return sorted(PERMISSION_CODES)


# ---------------------------------------------------------------------------
# Role assignment endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/studies/{study_id}/users/{user_id}/assign",
    response_model=UserResponse,
)
async def assign_roles(
    study_id: UUID,
    user_id: UUID,
    body: list[RoleAssignmentRequest],
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("user.assign"))],
) -> UserResponse:
    """Assign roles to a user within a study scope.

    Requirement 3.3: Role assignment with study/site scope.
    """
    # Inject study_id into assignments that don't have one
    for assignment in body:
        if assignment.study_id is None:
            assignment.study_id = study_id

    user = await user_service.assign_roles(
        session=session,
        user_id=user_id,
        assignments=body,
        actor_id=current_user.id,
    )
    return UserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# Invitation endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/auth/invite",
    response_model=InvitationResponse,
    status_code=201,
)
async def send_invitation(
    body: InvitationCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("user.create"))],
) -> InvitationResponse:
    """Send a user invitation with a role and optional scope.

    Requirement 3.1: Invite a user with a pending record and single-use token.
    """
    invitation = await user_service.invite(
        session=session, data=body, invited_by=current_user.id
    )
    return InvitationResponse.model_validate(invitation)


@router.post(
    "/auth/invite/accept",
    response_model=UserResponse,
    status_code=201,
)
async def accept_invitation(
    body: InvitationAcceptRequest,
    session: DbSession,
) -> UserResponse:
    """Accept an invitation and activate the user account.

    Requirement 3.2: Accept a valid invitation (no auth required).
    """
    try:
        user = await user_service.accept_invitation(
            session=session,
            token=body.token,
            password=body.password,
            first_name=body.first_name,
            last_name=body.last_name,
        )
        return UserResponse.model_validate(user)
    except InvitationError as exc:
        from app.core.exceptions import ValidationError

        raise ValidationError(message=str(exc)) from None
