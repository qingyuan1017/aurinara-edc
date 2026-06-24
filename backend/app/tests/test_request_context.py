"""Tests for request-ID middleware and request context (Requirements 21.5, 30.4)."""

import uuid

import pytest


@pytest.mark.asyncio
async def test_response_has_x_request_id_header(client):
    """Every response includes an X-Request-ID header with a valid UUID."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    req_id = response.headers.get("x-request-id")
    assert req_id is not None
    # Should be a valid UUID
    uuid.UUID(req_id)


@pytest.mark.asyncio
async def test_client_provided_request_id_is_echoed(client):
    """When the client sends X-Request-ID, the server echoes it back."""
    custom_id = str(uuid.uuid4())
    response = await client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == custom_id


@pytest.mark.asyncio
async def test_each_request_gets_unique_id(client):
    """Sequential requests without a client-provided ID each get a unique request_id."""
    resp1 = await client.get("/api/v1/health")
    resp2 = await client.get("/api/v1/health")
    id1 = resp1.headers.get("x-request-id")
    id2 = resp2.headers.get("x-request-id")
    assert id1 != id2


@pytest.mark.asyncio
async def test_request_id_is_uuid_format(client):
    """Auto-generated request IDs are valid UUID4 format."""
    response = await client.get("/api/v1/health")
    req_id = response.headers.get("x-request-id")
    parsed = uuid.UUID(req_id)
    assert parsed.version == 4
