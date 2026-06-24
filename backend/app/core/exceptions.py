"""Domain exceptions and centralized error-envelope handler.

Maps domain exceptions to the standard error envelope:
    {"error": {"code": "...", "message": "...", "details": {...}}}

Suppresses internal details (DB errors, stack traces) per Requirement 21.3.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class DomainError(Exception):
    """Base class for all domain exceptions."""

    def __init__(self, message: str = "An error occurred", details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(DomainError):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str = "Resource not found", details: dict[str, Any] | None = None):
        super().__init__(message=message, details=details)


class ValidationError(DomainError):
    """Raised when input validation fails at the domain layer."""

    def __init__(
        self, message: str = "Validation failed", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, details=details)


class AuthenticationError(DomainError):
    """Raised when authentication fails (invalid/missing credentials)."""

    def __init__(
        self, message: str = "Authentication required", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, details=details)


class AuthorizationError(DomainError):
    """Raised when the authenticated user lacks permission."""

    def __init__(
        self, message: str = "Insufficient permissions", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, details=details)


class ConflictError(DomainError):
    """Raised on uniqueness or state conflicts."""

    def __init__(
        self, message: str = "Resource conflict", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, details=details)


class BusinessRuleError(DomainError):
    """Raised when a business rule is violated."""

    def __init__(
        self, message: str = "Business rule violation", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, details=details)


# ---------------------------------------------------------------------------
# Exception → HTTP status mapping
# ---------------------------------------------------------------------------

_EXCEPTION_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ValidationError: 422,
    AuthenticationError: 401,
    AuthorizationError: 403,
    ConflictError: 409,
    BusinessRuleError: 400,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_request_id(request: Request) -> str | None:
    """Attempt to retrieve the request_id from request state or context.

    Returns None if no request_id is available (e.g., before the
    request-context middleware is implemented).
    """
    # First try request.state (set by middleware)
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id

    # Fallback: check the X-Request-ID header (may be echoed by middleware)
    return request.headers.get("x-request-id")


def _build_error_envelope(
    code: str, message: str, details: dict[str, Any], request_id: str | None = None
) -> dict[str, Any]:
    """Build the standard error envelope."""
    envelope: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }
    if request_id:
        envelope["error"]["request_id"] = request_id
    return envelope


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Handle all DomainError subclasses with the standard error envelope."""
    status_code = _EXCEPTION_STATUS_MAP.get(type(exc), 500)
    code = type(exc).__name__
    request_id = _get_request_id(request)

    return JSONResponse(
        status_code=status_code,
        content=_build_error_envelope(
            code=code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        ),
    )


# ---------------------------------------------------------------------------
# Catch-all middleware for unexpected exceptions
# ---------------------------------------------------------------------------


class ExceptionEnvelopeMiddleware(BaseHTTPMiddleware):
    """Catches any unhandled exception and returns the standard error envelope.

    This middleware sits above Starlette's exception handler layer, ensuring
    that even unexpected RuntimeErrors, DB failures, etc. are caught and
    converted to a safe 500 response without leaking internal details.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            # Domain errors are handled by the registered exception handler
            if isinstance(exc, DomainError):
                raise
            # Generic/unexpected — suppress internal details
            request_id = _get_request_id(request)
            logger.exception(
                "Unhandled exception [request_id=%s]: %s",
                request_id,
                str(exc),
            )
            return JSONResponse(
                status_code=500,
                content=_build_error_envelope(
                    code="InternalServerError",
                    message="An unexpected error occurred",
                    details={},
                    request_id=request_id,
                ),
            )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app instance."""
    # Register the base DomainError handler — FastAPI dispatches to the most
    # specific registered handler, so registering DomainError covers all subclasses.
    app.add_exception_handler(DomainError, domain_exception_handler)  # type: ignore[arg-type]

    # Middleware to catch unexpected exceptions (sits above Starlette's error layer)
    app.add_middleware(ExceptionEnvelopeMiddleware)
