"""Focused coverage for PV/Safety task 1.3 shared request context and API contracts.

**Validates: Requirements 16.1, 16.2, 16.3, 16.5, 24.2**

PV reuses the shared request-ID middleware, error envelope, sanitization, and
UTC serialization rather than forking them. The only PV-specific contract is the
pagination envelope, whose page size ranges from 1 through 1,000.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.api.routes.pv import router as pv_router
from app.core.exceptions import ConflictError, register_exception_handlers
from app.core.middleware import RequestIDMiddleware
from app.core.openapi import API_TAGS, install_openapi_metadata
from app.core.request_context import get_request_context
from app.schemas.base import BaseSchema
from app.schemas.pv import (
    PV_MAX_PAGE_SIZE,
    PVErrorCode,
    PVPaginatedResponse,
    PVPaginationContract,
    PVPaginationParams,
)


class _TimestampResponse(BaseSchema):
    occurred_at: datetime


@pytest.fixture
def pv_contract_app() -> FastAPI:
    """A minimal app exercising the shared PV request/error/pagination contracts."""

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/context")
    async def context(request: Request) -> dict[str, str | None]:
        ctx = get_request_context()
        return {
            "request_id": ctx.request_id,
            "correlation_id": ctx.correlation_id,
            "state_request_id": request.state.request_id,
        }

    @app.get("/sensitive-error")
    async def sensitive_error() -> None:
        # PV errors must never leak stack traces, internal database errors,
        # prohibited safety data, raw coordination payloads, or credentials.
        raise ConflictError(
            message="database password=top-secret traceback (internal)",
            details={
                "case_id": "case-1",
                "allowed_statuses": ["In Review", "Closed"],
                "Clinical_Data": {"value": "restricted"},
                "raw_event_body": {"value": "secret"},
                "projection_payload": {"seriousness": "serious"},
                "credential": "abc123",
            },
        )

    @app.get("/list")
    async def list_items(
        pagination: Annotated[PVPaginationParams, Depends()],
    ) -> PVPaginatedResponse[str]:
        return PVPaginatedResponse[str](
            items=["a", "b"],
            page=pagination.page,
            page_size=pagination.page_size,
            total=2,
        )

    return app


@pytest.mark.asyncio
async def test_request_and_correlation_context_are_propagated(pv_contract_app: FastAPI) -> None:
    """16.5: one request identifier is assigned, returned, and reusable downstream."""

    transport = ASGITransport(app=pv_contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/context",
            headers={"X-Request-ID": "pv-request-123", "X-Correlation-ID": "pv-correlation-456"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "pv-request-123",
        "correlation_id": "pv-correlation-456",
        "state_request_id": "pv-request-123",
    }
    assert response.headers["x-request-id"] == "pv-request-123"
    assert response.headers["x-correlation-id"] == "pv-correlation-456"


@pytest.mark.asyncio
async def test_request_id_is_generated_when_absent(pv_contract_app: FastAPI) -> None:
    """16.5: the middleware assigns an identifier and returns it even with no header."""

    transport = ASGITransport(app=pv_contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/context")

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["request_id"] == response.headers["x-request-id"]
    assert body["state_request_id"] == body["request_id"]


@pytest.mark.asyncio
async def test_pv_error_envelope_is_sanitized_and_keeps_trace_headers(
    pv_contract_app: FastAPI,
) -> None:
    """16.3: PV errors expose caller-safe details only, never sensitive content."""

    transport = ASGITransport(app=pv_contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/sensitive-error",
            headers={"X-Request-ID": "pv-request-123", "X-Correlation-ID": "pv-correlation-456"},
        )

    assert response.status_code == 409
    body = response.json()["error"]

    # Envelope shape is the baseline platform contract.
    assert set(body).issuperset({"code", "message", "details"})

    # The sensitive message is replaced; caller-safe fields survive.
    assert body["message"] == "Request could not be processed"
    assert body["details"] == {
        "case_id": "case-1",
        "allowed_statuses": ["In Review", "Closed"],
    }

    # No secret, clinical, payload, or credential content leaks anywhere.
    for leaked in ("secret", "top-secret", "restricted", "password", "abc123", "traceback"):
        assert leaked not in response.text.lower()

    assert response.headers["x-request-id"] == "pv-request-123"
    assert response.headers["x-correlation-id"] == "pv-correlation-456"


def test_base_schema_serializes_aware_datetimes_as_utc() -> None:
    """16.1: PV response schemas serialize timestamps as UTC ISO-8601."""

    value = datetime(2025, 1, 1, 12, 30, tzinfo=UTC) + timedelta(hours=2)
    response = _TimestampResponse(occurred_at=value)
    assert response.model_dump(mode="json")["occurred_at"] == "2025-01-01T14:30:00Z"


def test_pv_pagination_envelope_bounds() -> None:
    """16.2 / 24.2: page >= 1 and page size from 1 through 1,000."""

    # Valid boundaries.
    PVPaginatedResponse[str](items=[], page=1, page_size=1, total=0)
    PVPaginatedResponse[str](items=[], page=1, page_size=PV_MAX_PAGE_SIZE, total=0)

    # page must be >= 1.
    with pytest.raises(ValueError):
        PVPaginatedResponse[str](items=[], page=0, page_size=50, total=0)

    # page size must be within 1..1000.
    with pytest.raises(ValueError):
        PVPaginatedResponse[str](items=[], page=1, page_size=0, total=0)
    with pytest.raises(ValueError):
        PVPaginatedResponse[str](items=[], page=1, page_size=PV_MAX_PAGE_SIZE + 1, total=0)

    # total must be >= 0.
    with pytest.raises(ValueError):
        PVPaginatedResponse[str](items=[], page=1, page_size=50, total=-1)


def test_pv_pagination_envelope_allows_larger_pages_than_baseline() -> None:
    """24.2: PV lists may return up to 1,000 items per page, above the EDC/CTMS cap."""

    envelope = PVPaginatedResponse[str](items=[], page=2, page_size=1000, total=5000)
    dumped = envelope.model_dump()
    assert dumped["page"] == 2
    assert dumped["page_size"] == 1000
    assert dumped["total"] == 5000


@pytest.mark.asyncio
async def test_pv_pagination_params_enforce_bounds_at_the_boundary(
    pv_contract_app: FastAPI,
) -> None:
    """16.2 / 24.2: query params default sanely and reject out-of-range page sizes."""

    transport = ASGITransport(app=pv_contract_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        default = await client.get("/list")
        max_page = await client.get("/list", params={"page": 1, "page_size": 1000})
        too_large = await client.get("/list", params={"page": 1, "page_size": 1001})
        too_small = await client.get("/list", params={"page": 0, "page_size": 25})

    assert default.status_code == 200
    assert default.json()["page"] == 1
    assert default.json()["page_size"] == 50

    assert max_page.status_code == 200
    assert max_page.json()["page_size"] == 1000

    assert too_large.status_code == 422
    assert too_small.status_code == 422


def test_pv_openapi_metadata_is_published() -> None:
    """16.1: PV paths, enums, error codes, and pagination are discoverable in OpenAPI."""

    app = FastAPI(openapi_tags=API_TAGS)
    install_openapi_metadata(app)
    app.include_router(pv_router, prefix="/api/v1")
    schema = app.openapi()

    # PV routes are mounted under /api/v1/pv.
    assert "/api/v1/pv/capabilities" in schema["paths"]

    # PV tags are published alongside CTMS.
    tag_names = {tag["name"] for tag in schema["tags"]}
    assert {"pv", "pv-cases", "pv-audit"}.issubset(tag_names)

    info = schema["info"]
    # PV error codes and enum values are discoverable.
    assert PVErrorCode.PV_INVALID_TRANSITION.value in info["x-pv-error-codes"]
    assert PVErrorCode.OWNERSHIP_VIOLATION.value in info["x-pv-enums"]["pv_error_code"]
    assert "Closed" in info["x-pv-enums"]["case_state"]

    # The PV pagination contract advertises the 1..1000 page-size range.
    assert info["x-pv-pagination"]["schema"] == "PVPaginationContract"
    assert info["x-pv-pagination"]["properties"]["page_size"]["maximum"] == 1000

    # The pagination component schema is registered for client generation.
    assert "PVPaginationContract" in schema["components"]["schemas"]
    assert "PVErrorCode" in schema["components"]["schemas"]


def test_pv_pagination_contract_matches_envelope_bounds() -> None:
    """The OpenAPI-facing contract and the response envelope share the same bounds."""

    contract_schema = PVPaginationContract.model_json_schema()
    assert contract_schema["properties"]["page"]["minimum"] == 1
    assert contract_schema["properties"]["page_size"]["minimum"] == 1
    assert contract_schema["properties"]["page_size"]["maximum"] == 1000
    assert contract_schema["properties"]["total"]["minimum"] == 0
