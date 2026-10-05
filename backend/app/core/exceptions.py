"""Domain exceptions and centralized, sanitized API error envelopes."""

import logging
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.observability import sanitize_error
from app.core.request_context import get_correlation_id, get_request_id
from app.schemas.base import ErrorEnvelope

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for expected application errors."""

    def __init__(
        self,
        message: str = "An error occurred",
        details: dict[str, Any] | None = None,
        *,
        code: str | None = None,
    ):
        self.message = message
        self.details = details or {}
        self.code = code
        super().__init__(message)


class NotFoundError(DomainError):
    def __init__(self, message: str = "Resource not found", details: dict[str, Any] | None = None):
        super().__init__(message, details)


class ValidationError(DomainError):
    def __init__(self, message: str = "Validation failed", details: dict[str, Any] | None = None):
        super().__init__(message, details)


class AuthenticationError(DomainError):
    def __init__(self, message: str = "Authentication required", details: dict[str, Any] | None = None):
        super().__init__(message, details)


class AuthorizationError(DomainError):
    def __init__(self, message: str = "Insufficient permissions", details: dict[str, Any] | None = None):
        super().__init__(message, details)


class ConflictError(DomainError):
    def __init__(self, message: str = "Resource conflict", details: dict[str, Any] | None = None):
        super().__init__(message, details)


class BusinessRuleError(DomainError):
    def __init__(self, message: str = "Business rule violation", details: dict[str, Any] | None = None):
        super().__init__(message, details)


class ServiceUnavailableError(DomainError):
    def __init__(self, message: str = "Service unavailable", details: dict[str, Any] | None = None):
        super().__init__(message, details)


_EXCEPTION_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ValidationError: 422,
    AuthenticationError: 401,
    AuthorizationError: 403,
    ConflictError: 409,
    BusinessRuleError: 400,
    ServiceUnavailableError: 503,
}

# Error details are not a data transport. These names cover clinical values,
# credentials, raw event bodies, unrestricted messages, and infrastructure data.
_SENSITIVE_KEY = re.compile(
    r"clinical[_ .-]?data|field[_ .-]?value|form[_ .-]?instance|source[_ .-]?document|"
    r"credential|password|secret|token|authorization|event[_ .-]?body|event[_ .-]?payload|"
    r"raw[_ .-]?(event|body|payload)|payload|projection[_ .-]?(value|payload)|prohibited|"
    r"unrestricted|query[_ .-]?(message|body|text|history)|stack|traceback|"
    r"database|sqlalchemy|psycopg|connection[_ .-]?string",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"password\s*=|secret[_ -]?key\s*=|aws_secret|postgres(?:ql)?://|"
    r"traceback\s*\(|sqlalchemy|psycopg|event[_ .-]?(?:body|payload)|"
    r"raw\s+(?:event|body|payload)|clinical[_ .-]?data|prohibited\s+projection|"
    r"clinical[_ .-]?data|unrestricted\s+(?:query|message)|query[_ .-]?(?:message|body|text)",
    re.IGNORECASE,
)
_MAX_DETAIL_DEPTH = 5
_MAX_STRING_LENGTH = 512


def _safe_key(key: object) -> str:
    return str(key)[:128]


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    """Return JSON-safe details without sensitive or unrestricted content."""

    if depth > _MAX_DETAIL_DEPTH:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (UUID, datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            safe_key = _safe_key(key)
            if _SENSITIVE_KEY.search(safe_key):
                continue
            sanitized[safe_key] = _sanitize_value(child, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(child, depth=depth + 1) for child in list(value)[:100]]
    text = str(value)
    if _SENSITIVE_VALUE.search(text):
        return "[REDACTED]"
    return text[:_MAX_STRING_LENGTH]


def _sanitize_message(message: object) -> str:
    text = str(message)[:_MAX_STRING_LENGTH]
    return "Request could not be processed" if _SENSITIVE_VALUE.search(text) else text


def _trace_values(request: Request) -> tuple[str | None, str | None]:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    correlation_id = getattr(request.state, "correlation_id", None) or get_correlation_id()
    return request_id, correlation_id


def _get_request_id(request: Request) -> str | None:
    """Return the request identifier from state or the active context."""

    return _trace_values(request)[0]


def _build_error_envelope(
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Build the standard error envelope using only sanitized content."""

    envelope = ErrorEnvelope(
        error={
            "code": code,
            "message": _sanitize_message(message),
            "details": _sanitize_value(details or {}),
            "request_id": request_id,
            "correlation_id": correlation_id,
        }
    )
    return envelope.model_dump(mode="json", exclude_none=True)


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    request_id, correlation_id = _trace_values(request)
    response = JSONResponse(
        status_code=status_code,
        content=_build_error_envelope(code, message, details, request_id, correlation_id),
    )
    if request_id:
        response.headers["X-Request-ID"] = request_id
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    return response


async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_code = next(
        (status for exception_type, status in _EXCEPTION_STATUS_MAP.items() if isinstance(exc, exception_type)),
        500,
    )
    code = getattr(exc, "code", None)
    if not code:
        code = "ValidationError" if isinstance(exc, ValidationError) else type(exc).__name__
        reason = exc.details.get("reason")
        # CTMS and coordination reasons are stable public codes.  Only promote
        # the allowlisted namespaces; arbitrary detail values remain details.
        if isinstance(reason, str) and (
            reason.startswith(("CTMS_", "COORDINATION_", "PV_"))
            or reason in {
                "RECORD_NOT_FOUND",
                "AMBIGUOUS_REFERENCE",
                "AUTHORIZATION_FAILED",
                "OWNERSHIP_VIOLATION",
                "DATA_MINIMIZATION_FAILED",
                "PROJECTION_FIELD_NOT_ALLOWED",
            }
        ):
            code = reason
    return _response(
        request,
        status_code=status_code,
        code=code,
        message=exc.message,
        details=exc.details,
    )


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = {
        "validation_errors": [
            {
                "loc": list(error.get("loc", ())),
                "message": error.get("msg", "Invalid request"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
    }
    return _response(
        request,
        status_code=422,
        code="ValidationError",
        message="Request validation failed",
        details=details,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalize FastAPI/Starlette errors into the shared envelope."""

    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _response(
        request,
        status_code=exc.status_code,
        code=f"HTTP_{exc.status_code}",
        message=detail,
    )


class ExceptionEnvelopeMiddleware(BaseHTTPMiddleware):
    """Convert unexpected failures to a safe 500 response and trace headers."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except DomainError:
            raise
        except Exception as exc:
            request_id, correlation_id = _trace_values(request)
            logger.error(
                "Unhandled exception [request_id=%s correlation_id=%s] category=%s",
                request_id,
                correlation_id,
                sanitize_error(exc)["category"],
            )
            return _response(
                request,
                status_code=500,
                code="InternalServerError",
                message="An unexpected error occurred",
            )


def register_exception_handlers(app: FastAPI) -> None:
    """Register shared handlers for domain, validation, HTTP, and unknown errors."""

    app.add_exception_handler(DomainError, domain_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    # Starlette raises its own HTTPException for unmatched routes and method
    # mismatches; register it explicitly so CTMS boundary failures use the same
    # sanitized envelope and request-ID contract as domain failures.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_middleware(ExceptionEnvelopeMiddleware)
