"""Focused coverage for CTMS task 1.3 shared API contracts.

**Validates: Requirements 1.7, 1.9, 2.5, 11.2, 11.7-11.10**
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.api.routes.ctms import router as ctms_router
from app.core.exceptions import NotFoundError, register_exception_handlers
from app.core.middleware import RequestIDMiddleware
from app.core.openapi import API_TAGS, install_openapi_metadata
from app.core.request_context import get_request_context
from app.schemas.base import BaseSchema, PaginatedResponse


class TimestampResponse(BaseSchema):
    occurred_at: datetime


@pytest.fixture
def contract_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/context")
    async def context(request: Request) -> dict[str, str | None]:
        context = get_request_context()
        return {
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "state_request_id": request.state.request_id,
        }

    @app.get("/sensitive-error")
    async def sensitive_error() -> None:
        raise NotFoundError(
            message="database password=top-secret traceback (internal)",
            details={
                "id": "record-1",
                "Clinical_Data": {"value": "restricted"},
                "raw_event_body": {"value": "secret"},
                "query_id": "query-1",
                "query_message": "unrestricted clinical message",
                "safe": {"reason": "not ready"},
            },
        )

    return app


@pytest.mark.asyncio
async def test_request_and_correlation_context_are_propagated(contract_app: FastAPI) -> None:
    transport = ASGITransport(app=contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/context",
            headers={"X-Request-ID": "request-123", "X-Correlation-ID": "correlation-456"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "request-123",
        "correlation_id": "correlation-456",
        "state_request_id": "request-123",
    }
    assert response.headers["x-request-id"] == "request-123"
    assert response.headers["x-correlation-id"] == "correlation-456"


@pytest.mark.asyncio
async def test_error_envelope_sanitizes_sensitive_content_and_keeps_trace_headers(
    contract_app: FastAPI,
) -> None:
    transport = ASGITransport(app=contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/sensitive-error",
            headers={"X-Request-ID": "request-123", "X-Correlation-ID": "correlation-456"},
        )

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["message"] == "Request could not be processed"
    assert body["details"] == {"id": "record-1", "query_id": "query-1", "safe": {"reason": "not ready"}}
    assert "secret" not in response.text
    assert response.headers["x-request-id"] == "request-123"
    assert response.headers["x-correlation-id"] == "correlation-456"


def test_base_schema_serializes_aware_datetimes_as_utc() -> None:
    value = datetime(2025, 1, 1, 12, 30, tzinfo=UTC) + timedelta(hours=2)
    response = TimestampResponse(occurred_at=value)
    assert response.model_dump(mode="json")["occurred_at"] == "2025-01-01T14:30:00Z"


def test_pagination_contract_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        PaginatedResponse[str](items=[], page=0, page_size=25, total=0)
    with pytest.raises(ValueError):
        PaginatedResponse[str](items=[], page=1, page_size=101, total=0)


def test_ctms_openapi_metadata_is_published() -> None:
    app = FastAPI(openapi_tags=API_TAGS)
    install_openapi_metadata(app)
    app.include_router(ctms_router, prefix="/api/v1")
    schema = app.openapi()
    assert "/api/v1/ctms/capabilities" in schema["paths"]
    tag_names = {tag["name"] for tag in schema["tags"]}
    assert {"ctms", "ctms-studies", "ctms-projections"}.issubset(tag_names)
    assert "COORDINATION_CONFLICT" in schema["info"]["x-ctms-error-codes"]
    assert schema["info"]["x-module-ownership"]["CTMS"].startswith("operational")
