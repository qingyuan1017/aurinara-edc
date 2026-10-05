"""FastAPI dependencies — session, current user, permission guards.

These are injected into route handlers to keep them thin (Requirement 23.1).

Permission guards satisfy:
  - 2.2: Route-level permission enforcement by study/site scope.
  - 2.3: Authorization error when scope lacks required permission.
  - 23.1: Thin route handlers delegate to dependencies.
  - 23.4: Every protected operation passes through Permission_Service before mutation.
"""

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.request_context import set_actor
from app.core.security import (
    InvalidTokenError,
    decode_token,
    validate_cognito_token,
)
from app.models.identity import Role, RolePermission, User, UserRole, UserStatus
from app.services.permission_service import PermissionService

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session with auto-commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> User:
    """Resolve the authenticated user from the Authorization header.

    Strategy (Requirement 1.1, 1.7):
      1. Extract the Bearer token from the Authorization header.
      2. Attempt to decode as a locally issued JWT.
      3. If local decode fails and Cognito is configured, try validate_cognito_token.
      4. Load the internal User with relationships.
      5. Reject inactive users (Requirement 3.5).
      6. Set actor_var in request context for audit/logging correlation.

    Raises:
        AuthenticationError: If the token is missing, invalid, or maps to
            no active internal user.
    """
    if credentials is None:
        raise AuthenticationError("Missing authentication credentials")

    token = credentials.credentials
    user_id: UUID | None = None

    # --- Attempt 1: local JWT decode ---
    try:
        payload = decode_token(token)
        if payload.type != "access":
            raise InvalidTokenError("Token is not an access token")
        user_id = UUID(payload.sub)
    except InvalidTokenError:
        # --- Attempt 2: Cognito/OIDC validation (if configured) ---
        cognito_payload = validate_cognito_token(token)
        if cognito_payload is None:
            # Cognito not configured and local decode failed
            raise AuthenticationError(
                "Invalid or expired token"
            ) from None

        # Map Cognito subject to internal user via email
        if cognito_payload.email:
            result = await session.execute(
                select(User).where(User.email == cognito_payload.email)
            )
            user = result.scalars().first()
            if user is None:
                raise AuthenticationError(
                    f"No internal user mapped to external identity: {cognito_payload.sub}"
                ) from None
            user_id = user.id
        else:
            raise AuthenticationError(
                "Cognito token missing email claim for user mapping"
            ) from None

    # --- Load user with role relationships ---
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.user_roles)
            .selectinload(UserRole.role)
            .selectinload(Role.role_permissions)
            .selectinload(RolePermission.permission)
        )
    )
    user = result.scalars().first()

    if user is None:
        raise AuthenticationError("User not found")

    if user.status == UserStatus.inactive:
        raise AuthenticationError("Account is inactive")

    # --- Set actor context for audit/logging and request inspection ---
    set_actor(user.id)
    request.state.actor_id = user.id

    return user


# Type alias for use as a dependency annotation in route handlers
CurrentUser = Annotated[User, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# Permission service dependency
# ---------------------------------------------------------------------------

_permission_service_instance: PermissionService | None = None


def get_permission_service() -> PermissionService:
    """Return the PermissionService singleton."""
    global _permission_service_instance
    if _permission_service_instance is None:
        _permission_service_instance = PermissionService()
    return _permission_service_instance


# ---------------------------------------------------------------------------
# Permission guard dependencies (Requirements 2.2, 2.3, 23.1, 23.4)
# ---------------------------------------------------------------------------


def _extract_uuid(request: Request, param_name: str) -> UUID | None:
    """Extract a UUID from path params, falling back to query params.

    Returns None if the parameter is not present or cannot be parsed as UUID.
    """
    # Try path parameters first
    value = request.path_params.get(param_name)
    if value is not None:
        try:
            return UUID(str(value))
        except (ValueError, TypeError):
            return None

    # Fallback to query parameters
    value = request.query_params.get(param_name)
    if value is not None:
        try:
            return UUID(str(value))
        except (ValueError, TypeError):
            return None

    return None


def require_permission(permission: str) -> Callable:
    """Return a FastAPI dependency that enforces a permission.

    Usage in route handlers:
        @router.post("/...", dependencies=[Depends(require_permission("form.enter"))])
        async def create_form(...): ...

    Or to also receive the user:
        user: User = Depends(require_permission("form.enter"))

    The guard extracts study_id and site_id from path parameters if present,
    calls Permission_Service.require, and raises 403 on failure.
    Returns the authenticated User on success.

    Requirements 2.2, 2.3, 23.4.
    """

    async def _guard(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
        permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    ) -> User:
        study_id = _extract_uuid(request, "study_id")
        site_id = _extract_uuid(request, "site_id")

        try:
            permission_service.require(
                current_user, permission, study_id=study_id, site_id=site_id
            )
        except AuthorizationError:
            raise AuthorizationError(
                message="Insufficient permissions",
                details={
                    "required_permission": permission,
                    "study_id": str(study_id) if study_id else None,
                    "site_id": str(site_id) if site_id else None,
                },
            ) from None

        return current_user

    return _guard


def require_ctms_permission(permission: str) -> Callable:
    """Return the shared server-side guard for a CTMS operation.

    CTMS routes use the same dependency implementation and error envelope as
    EDC routes. Keeping a named factory makes CTMS mutation declarations
    explicit while preventing a second authorization model from emerging.
    """
    return require_permission(permission)


def require_pv_permission(permission: str) -> Callable:
    """Return the shared server-side guard for a PV/Safety operation.

    PV routes use the same shared ``Auth_Service``/``Permission_Service`` and
    error envelope as EDC and CTMS routes; there is no separate PV identity or
    authorization model. The guard:

      - rejects unauthenticated/inactive users at ``get_current_user`` and again
        inside ``PermissionService`` before any mutation (Requirements 1.4, 2.x),
      - resolves the required PV Permission against the target study/site scope
        drawn from path/query params before the route runs (Requirement 18.4),
      - denies site-scope actions after a role/scope removal because the scope
        is resolved live from the user's current role assignments,
      - returns a non-disclosing ``PV_SCOPE_DENIED`` access-denied indication
        that does not reveal whether the target object exists (Requirement 2.4).

    PV roles resolve through the same shared Permission_Service and cannot
    mutate EDC clinical or CTMS operational records because no PV role is granted
    an EDC/CTMS mutation permission code.
    """

    async def _guard(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
        permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    ) -> User:
        study_id = _extract_uuid(request, "study_id")
        site_id = _extract_uuid(request, "site_id")

        try:
            permission_service.require(
                current_user, permission, study_id=study_id, site_id=site_id
            )
        except AuthorizationError:
            # Non-disclosing: do not reveal whether the object exists or which of
            # the study/site scopes was missing beyond the requested permission.
            raise AuthorizationError(
                message="Access denied",
                details={
                    "reason": "PV_SCOPE_DENIED",
                    "required_permission": permission,
                },
            ) from None

        return current_user

    return _guard


def require_pv_object_access(permission: str, obj_getter: Callable) -> Callable:
    """Return a PV guard that enforces object-level scope (Requirements 2.4, 2.5).

    ``obj_getter`` is an async dependency that loads the target PV object (for
    example a Safety_Case) using the shared session. The guard first requires
    the PV ``permission`` at the object's resolved study/site scope, then asserts
    object-level access so a caller cannot reach a record outside their
    Authorization_Scope. Both failures return the same non-disclosing
    ``PV_SCOPE_DENIED`` indication that does not disclose object existence.
    """

    async def _guard(
        current_user: Annotated[User, Depends(get_current_user)],
        permission_service: Annotated[PermissionService, Depends(get_permission_service)],
        obj: Annotated[object, Depends(obj_getter)],
    ) -> User:
        obj_study_id = getattr(obj, "study_id", None)
        obj_site_id = getattr(obj, "site_id", None)
        try:
            permission_service.require(
                current_user, permission, study_id=obj_study_id, site_id=obj_site_id
            )
            permission_service.assert_object_access(current_user, obj)
        except AuthorizationError:
            raise AuthorizationError(
                message="Access denied",
                details={
                    "reason": "PV_SCOPE_DENIED",
                    "required_permission": permission,
                },
            ) from None

        return current_user

    return _guard


class PermissionGuard:
    """A flexible, parameterizable permission guard dependency.

    Usage:
        @router.get("/...", dependencies=[Depends(PermissionGuard("form.read"))])
        async def read_forms(...): ...

    Or to obtain the user:
        user: User = Depends(PermissionGuard("form.enter"))

    Extracts study_id and site_id from both path parameters and query parameters,
    giving path params precedence.

    Requirements 2.2, 2.3, 23.4.
    """

    def __init__(self, permission: str) -> None:
        self.permission = permission

    async def __call__(
        self,
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
        permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    ) -> User:
        """Enforce the permission and return the authenticated user."""
        study_id = _extract_uuid(request, "study_id")
        site_id = _extract_uuid(request, "site_id")

        try:
            permission_service.require(
                current_user, self.permission, study_id=study_id, site_id=site_id
            )
        except AuthorizationError:
            raise AuthorizationError(
                message="Insufficient permissions",
                details={
                    "required_permission": self.permission,
                    "study_id": str(study_id) if study_id else None,
                    "site_id": str(site_id) if site_id else None,
                },
            ) from None

        return current_user


class CTMSPermissionGuard(PermissionGuard):
    """Named class dependency for CTMS routes.

    It intentionally inherits the shared guard so inactive-user checks,
    study/site extraction, and baseline ``AuthorizationError`` behavior remain
    identical across EDC and CTMS.
    """


@dataclass
class PaginationParams:
    """Query-string pagination parameters.

    Injected as a dependency into list endpoints.
    Defaults: page=1, page_size=25. Max page_size=100.

    Satisfies Requirements 21.2 and 29.2.
    """

    page: int = Query(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Query(
        default=25, ge=1, le=100, description="Items per page (max 100)"
    )

    @property
    def offset(self) -> int:
        """Compute the SQL OFFSET from page and page_size."""
        return (self.page - 1) * self.page_size
