"""Focused CTMS API ownership, error, pagination, and OpenAPI contracts.

**Validates: Requirements 1.8, 8.8-8.9, 9.10-9.16, 11.7-11.10, 13.13**
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.ctms import router as ctms_router
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestIDMiddleware
from app.core.openapi import API_TAGS, install_openapi_metadata
from app.schemas.base import PaginatedResponse
from app.services.ctms_ownership_guard import CTMSOwnershipError


def test_ctms_openapi_publishes_contract_vocabulary_and_responses() -> None:
    app = FastAPI(openapi_tags=API_TAGS)
    install_openapi_metadata(app)
    app.include_router(ctms_router, prefix="/api/v1")

    schema = app.openapi()
    info = schema["info"]
    components = schema["components"]["schemas"]

    assert "CTMSErrorEnvelope" in components
    assert "CTMSPaginationContract" in components
    assert "CTMSErrorCode" in components
    assert "CoordinationEventType" in components
    assert "CoordinationFailureCode" in components
    assert "CoordinationConflictCode" in components
    assert "CoordinationEventStatus" in components

    assert "CTMS_OWNERSHIP_CONFLICT" in info["x-ctms-error-codes"]
    assert "RECORD_NOT_FOUND" in info["x-ctms-failure-codes"]
    assert "AMBIGUOUS_REFERENCE" in info["x-ctms-failure-codes"]
    assert "COORDINATION_OUT_OF_ORDER" in info["x-ctms-conflict-codes"]
    assert "CTMS_PROJECTION_UPDATED" in info["x-ctms-event-types"]
    assert set(info["x-ctms-projection-states"]) == {
        "current",
        "stale",
        "rejected",
        "archived",
    }
    assert info["x-ctms-pagination"]["properties"]["page_size"]["maximum"] == 100
    assert info["x-ctms-ownership-rules"][0]["authoritative_module"] == "EDC"

    event_path = schema["paths"]["/api/v1/ctms/coordination-events/{event_id}/replay"]["post"]
    assert "409" in event_path["responses"]
    assert event_path["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/CTMSErrorEnvelope"
    )


def test_paginated_response_has_the_shared_ctms_shape() -> None:
    response = PaginatedResponse[str](items=["one"], page=1, page_size=25, total=1)
    assert response.model_dump() == {
        "items": ["one"],
        "page": 1,
        "page_size": 25,
        "total": 1,
    }


async def _raise_ownership_error() -> None:
    raise CTMSOwnershipError(field="clinical_data.value", operation="update_task")


async def test_ownership_conflicts_use_explicit_code_and_sanitized_details() -> None:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.add_api_route("/ownership", _raise_ownership_error, methods=["POST"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/ownership",
            headers={"X-Request-ID": "request-6-2", "X-Correlation-ID": "correlation-6-2"},
        )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CTMS_OWNERSHIP_CONFLICT"
    assert error["details"] == {
        "reason": "EDC_OWNERSHIP_VIOLATION",
        "field": "[REDACTED]",
        "operation": "update_task",
        "authoritative_module": "EDC",
    }
    assert "secret" not in response.text
    assert "stack" not in response.text.lower()
    assert response.headers["x-request-id"] == "request-6-2"
    assert response.headers["x-correlation-id"] == "correlation-6-2"
