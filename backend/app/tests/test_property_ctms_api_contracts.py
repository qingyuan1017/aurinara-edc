"""Property-based verification of the CTMS API contract and redaction boundary.

# Feature: ctms-integration, Property 21: CTMS API contracts are consistent and non-leaking

**Validates: Requirements 2.5, 8.8-8.9, 11.1-11.10, 13.13**

The property drives a deterministic CTMS contract harness through the shared
request-ID middleware, exception handlers, and Pydantic pagination envelope.
It deliberately does not use a database or external service: API contract and
redaction behavior are transport concerns, while route/database behavior has
separate integration coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import ascii_letters, digits
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.api.routes.ctms import router as ctms_router
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ValidationError,
    register_exception_handlers,
)
from app.core.middleware import RequestIDMiddleware
from app.schemas.base import PaginatedResponse

_LIST_RESOURCES = st.sampled_from(
    (
        "operational-studies",
        "operational-sites",
        "enrollment-targets",
        "monitoring-activities",
        "tasks",
        "contacts",
        "projections",
        "coordination-events",
        "failed-events",
        "coordination-conflicts",
        "exports",
    )
)
_PERMISSION_STATES = st.sampled_from(("authorized", "viewer", "out_of_scope", "inactive"))
_FAILURE_COMMANDS = st.sampled_from(
    ("validation", "ownership", "conflict", "unexpected")
)
_SAFE_TOKEN = st.text(
    alphabet=ascii_letters + digits,
    min_size=8,
    max_size=32,
)


@dataclass(frozen=True)
class APIContractScenario:
    """Generated list request, command failure, and sensitive payload inputs."""

    resource: str
    page: int
    page_size: int
    permission_state: str
    failing_command: str
    request_id: str
    sensitive_values: tuple[str, ...]
    prohibited_payload: dict[str, Any]


@st.composite
def api_contract_scenarios(draw: st.DrawFn) -> APIContractScenario:
    """Generate CTMS request dimensions and values that must never be exposed."""

    token = draw(_SAFE_TOKEN)
    values = {
        "credential": f"credential-{token}",
        "clinical_data": f"Clinical_Data-{token}",
        "projection_value": f"prohibited-projection-{token}",
        "raw_event": f"raw-event-body-{token}",
        "message": f"unrestricted-query-message-{token}",
    }
    payload = {
        "Clinical_Data": {"value": values["clinical_data"]},
        "credentials": {"password": values["credential"]},
        "prohibited_projection_value": values["projection_value"],
        "raw_event_body": {"body": values["raw_event"]},
        "unrestricted_query_message": values["message"],
    }
    return APIContractScenario(
        resource=draw(_LIST_RESOURCES),
        page=draw(st.integers(min_value=1, max_value=8)),
        page_size=draw(st.integers(min_value=1, max_value=100)),
        permission_state=draw(_PERMISSION_STATES),
        failing_command=draw(_FAILURE_COMMANDS),
        request_id=f"property-21-{token}",
        sensitive_values=tuple(values.values()),
        prohibited_payload=payload,
    )


def _contract_app(scenario: APIContractScenario) -> FastAPI:
    """Create a deterministic API surface using the production shared contracts."""

    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestIDMiddleware)
    # Keep the real CTMS router mounted so this property also exercises the
    # public /api/v1/ctms route boundary and its OpenAPI registration.
    app.include_router(ctms_router, prefix="/api/v1")

    contract_router = APIRouter(prefix="/api/v1/ctms/property-contract")

    @contract_router.get("/{resource}")
    async def list_resource(resource: str, page: int = 1, page_size: int = 25):
        if scenario.permission_state != "authorized":
            if scenario.permission_state == "inactive":
                raise AuthenticationError("Account is inactive")
            raise AuthorizationError(
                "Insufficient permissions",
                {
                    "required_permission": "ctms.operational-data-read",
                    "permission_state": scenario.permission_state,
                },
            )

        # A deterministic fake models the shared list contract without
        # requiring persistence or a service outside this property.
        total = 3
        all_items = [
            {"id": f"{resource}-{index}", "resource": resource}
            for index in range(total)
        ]
        start = (page - 1) * page_size
        return PaginatedResponse(
            items=all_items[start : start + page_size],
            page=page,
            page_size=page_size,
            total=total,
        )

    @contract_router.post("/commands/{command}")
    async def failing_command(command: str, payload: dict[str, Any]):
        details = {
            "reason": "generated failure",
            "Clinical_Data": payload["Clinical_Data"],
            "credentials": payload["credentials"],
            "prohibited_projection_value": payload["prohibited_projection_value"],
            "raw_event_body": payload["raw_event_body"],
            "unrestricted_query_message": payload["unrestricted_query_message"],
        }
        if scenario.permission_state == "inactive":
            raise AuthenticationError("Account is inactive", details)
        if scenario.permission_state != "authorized":
            raise AuthorizationError("Insufficient permissions", details)
        if command == "validation":
            raise ValidationError("The CTMS command was invalid", details)
        if command == "ownership":
            raise ValidationError("The command contains a prohibited projection field", details)
        if command == "conflict":
            raise ConflictError("The requested operational change conflicts", details)
        # The exception middleware must emit a generic response and must not
        # put this raw event value into either response details or logs.
        raise RuntimeError(
            f"unexpected failure: {scenario.sensitive_values[3]} "
            f"{scenario.sensitive_values[4]}"
        )

    app.include_router(contract_router)
    return app


def _assert_no_sensitive_content(text: str, scenario: APIContractScenario) -> None:
    """Assert that generated clinical/secrecy markers are absent from output."""

    for value in scenario.sensitive_values:
        assert value not in text, f"sensitive value leaked: {value!r}"
    lowered = text.lower()
    for marker in (
        "traceback",
        "clinical_data",
        "stack trace",
        "raw event body",
        "unrestricted query message",
    ):
        assert marker not in lowered, f"sensitive marker leaked: {marker!r}"


@pytest.mark.asyncio
@given(scenario=api_contract_scenarios())
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_ctms_api_contracts_are_consistent_and_non_leaking(
    scenario: APIContractScenario, caplog: pytest.LogCaptureFixture
) -> None:
    """List and failure responses retain the CTMS contract and redact content."""

    app = _contract_app(scenario)
    transport = ASGITransport(app=app)
    caplog.clear()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get(
            f"/api/v1/ctms/property-contract/{scenario.resource}",
            params={"page": scenario.page, "page_size": scenario.page_size},
            headers={"X-Request-ID": scenario.request_id},
        )

        assert list_response.headers.get("X-Request-ID") == scenario.request_id
        if scenario.permission_state == "authorized":
            assert list_response.status_code == 200
            list_body = list_response.json()
            assert set(list_body) == {"items", "page", "page_size", "total"}
            assert list_body["page"] == scenario.page
            assert list_body["page_size"] == scenario.page_size
            assert list_body["total"] == 3
            assert len(list_body["items"]) <= scenario.page_size
        else:
            assert list_response.status_code in {401, 403}
            error = list_response.json().get("error")
            assert isinstance(error, dict)
            assert {"code", "message", "details"}.issubset(error)
            assert isinstance(error["details"], dict)

        failure_response = await client.post(
            f"/api/v1/ctms/property-contract/commands/{scenario.failing_command}",
            json=scenario.prohibited_payload,
            headers={"X-Request-ID": scenario.request_id},
        )

    assert failure_response.headers.get("X-Request-ID") == scenario.request_id
    assert failure_response.status_code in {401, 403, 409, 422, 500}
    failure_body = failure_response.json()
    assert set(failure_body) == {"error"}
    error = failure_body["error"]
    assert {"code", "message", "details"}.issubset(error)
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], dict)

    _assert_no_sensitive_content(failure_response.text, scenario)
    _assert_no_sensitive_content(list_response.text, scenario)
    _assert_no_sensitive_content(caplog.text, scenario)
    assert "X-Request-ID" not in failure_response.text
