"""Tests for the standard error envelope and exception mapping (Requirement 21.3)."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BusinessRuleError,
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)


@pytest.fixture
def error_app():
    """Create a test app with routes that raise domain exceptions."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    async def raise_not_found():
        raise NotFoundError(message="Study not found", details={"id": "abc-123"})

    @app.get("/validation")
    async def raise_validation():
        raise ValidationError(
            message="Field validation failed",
            details={"fields": {"email": "Invalid email format"}},
        )

    @app.get("/authentication")
    async def raise_authentication():
        raise AuthenticationError()

    @app.get("/authorization")
    async def raise_authorization():
        raise AuthorizationError(message="Cannot access study X")

    @app.get("/conflict")
    async def raise_conflict():
        raise ConflictError(message="Study code already exists", details={"code": "STUDY-001"})

    @app.get("/business-rule")
    async def raise_business_rule():
        raise BusinessRuleError(message="Cannot transition from Draft to Locked")

    @app.get("/domain-base")
    async def raise_domain_base():
        raise DomainError(message="Generic domain error")

    @app.get("/unexpected")
    async def raise_unexpected():
        raise RuntimeError("DB connection lost: host=10.0.0.5 port=5432 password=secret")

    return app


@pytest.fixture
async def error_client(error_app):
    """Async client for the error test app."""
    transport = ASGITransport(app=error_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Domain exception tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_error_returns_404(error_client):
    """NotFoundError maps to 404 with the standard envelope."""
    response = await error_client.get("/not-found")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "NotFoundError"
    assert body["error"]["message"] == "Study not found"
    assert body["error"]["details"] == {"id": "abc-123"}


@pytest.mark.asyncio
async def test_validation_error_returns_422(error_client):
    """ValidationError maps to 422 with field-level details."""
    response = await error_client.get("/validation")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "ValidationError"
    assert body["error"]["message"] == "Field validation failed"
    assert "fields" in body["error"]["details"]


@pytest.mark.asyncio
async def test_authentication_error_returns_401(error_client):
    """AuthenticationError maps to 401."""
    response = await error_client.get("/authentication")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AuthenticationError"
    assert body["error"]["message"] == "Authentication required"


@pytest.mark.asyncio
async def test_authorization_error_returns_403(error_client):
    """AuthorizationError maps to 403."""
    response = await error_client.get("/authorization")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "AuthorizationError"
    assert body["error"]["message"] == "Cannot access study X"


@pytest.mark.asyncio
async def test_conflict_error_returns_409(error_client):
    """ConflictError maps to 409."""
    response = await error_client.get("/conflict")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "ConflictError"
    assert body["error"]["details"] == {"code": "STUDY-001"}


@pytest.mark.asyncio
async def test_business_rule_error_returns_400(error_client):
    """BusinessRuleError maps to 400."""
    response = await error_client.get("/business-rule")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "BusinessRuleError"
    assert body["error"]["message"] == "Cannot transition from Draft to Locked"


@pytest.mark.asyncio
async def test_base_domain_error_returns_500(error_client):
    """A bare DomainError (no specific mapping) returns 500."""
    response = await error_client.get("/domain-base")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "DomainError"
    assert body["error"]["message"] == "Generic domain error"


# ---------------------------------------------------------------------------
# Generic/unexpected exception tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_exception_returns_500_generic(error_client):
    """Unexpected exceptions return 500 with a generic message — no leaks."""
    response = await error_client.get("/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "InternalServerError"
    assert body["error"]["message"] == "An unexpected error occurred"
    # Must NOT leak internal details
    assert "DB connection" not in str(body)
    assert "password" not in str(body)
    assert "host=" not in str(body)
    assert body["error"]["details"] == {}


# ---------------------------------------------------------------------------
# Envelope structure tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_envelope_structure(error_client):
    """All error responses follow the {error: {code, message, details}} structure."""
    for path in [
        "/not-found",
        "/validation",
        "/authentication",
        "/authorization",
        "/conflict",
        "/business-rule",
        "/unexpected",
    ]:
        response = await error_client.get(path)
        body = response.json()
        assert "error" in body, f"Missing 'error' key for {path}"
        error = body["error"]
        assert "code" in error, f"Missing 'code' for {path}"
        assert "message" in error, f"Missing 'message' for {path}"
        assert "details" in error, f"Missing 'details' for {path}"
        assert isinstance(error["code"], str)
        assert isinstance(error["message"], str)
        assert isinstance(error["details"], dict)


# ---------------------------------------------------------------------------
# Request-ID inclusion test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_id_included_when_available():
    """When request.state.request_id is set, it appears in the error envelope."""
    from starlette.middleware.base import BaseHTTPMiddleware

    app = FastAPI()
    register_exception_handlers(app)

    class FakeRequestIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.request_id = "test-req-id-42"
            return await call_next(request)

    app.add_middleware(FakeRequestIdMiddleware)

    @app.get("/fail")
    async def fail():
        raise NotFoundError(message="Gone")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/fail")
        body = response.json()
        assert body["error"]["request_id"] == "test-req-id-42"
