"""Property-based tests for request-id propagation.

**Validates: Requirements 21.5, 30.4**

Property 19: Request identifier is returned and propagated.

Uses Hypothesis to verify that:
1. Every response always contains an X-Request-ID header.
2. When a client sends an X-Request-ID, the response echoes the same value.
3. When no X-Request-ID is sent, the server generates a valid UUID4.
"""

import uuid

import pytest
from hypothesis import given, settings, strategies as st
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid API paths that exist on the app (health endpoints)
valid_paths = st.sampled_from([
    "/api/v1/health",
    "/api/v1/health/live",
])

# Generate valid UUID4 strings for X-Request-ID header
uuid4_strategy = st.uuids(version=4).map(str)

# Optional X-Request-ID: either a valid UUID4 string or None (not sent)
optional_request_id = st.one_of(uuid4_strategy, st.none())


# ---------------------------------------------------------------------------
# Property 19: Request identifier is returned and propagated
# ---------------------------------------------------------------------------


class TestRequestIdPropagation:
    """Property-based tests for X-Request-ID middleware behavior.

    **Validates: Requirements 21.5, 30.4**
    """

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Create a fresh app for each test class instance."""
        self.app = create_app()

    @settings(max_examples=100)
    @given(path=valid_paths, request_id=optional_request_id)
    @pytest.mark.anyio
    async def test_response_always_contains_request_id(self, path: str, request_id: str | None):
        """Every response MUST contain an X-Request-ID header regardless of
        whether the client sent one."""
        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {}
            if request_id is not None:
                headers["X-Request-ID"] = request_id

            response = await client.get(path, headers=headers)

            # The response must always have the header
            assert "x-request-id" in response.headers

    @settings(max_examples=100)
    @given(path=valid_paths, request_id=uuid4_strategy)
    @pytest.mark.anyio
    async def test_client_request_id_echoed(self, path: str, request_id: str):
        """When the client sends an X-Request-ID, the server MUST echo the
        exact same value back in the response header."""
        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path, headers={"X-Request-ID": request_id})

            assert response.headers["x-request-id"] == request_id

    @settings(max_examples=100)
    @given(path=valid_paths)
    @pytest.mark.anyio
    async def test_server_generates_valid_uuid4_when_no_header(self, path: str):
        """When no X-Request-ID is sent, the server MUST generate a valid
        UUID4 and return it in the response header."""
        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)

            returned_id = response.headers["x-request-id"]

            # Must be a valid UUID
            parsed = uuid.UUID(returned_id)

            # Must be version 4
            assert parsed.version == 4

    @settings(max_examples=100)
    @given(path=valid_paths)
    @pytest.mark.anyio
    async def test_generated_ids_are_unique(self, path: str):
        """When no X-Request-ID is sent, each request generates a distinct
        identifier (collision probability is negligible for UUID4)."""
        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response1 = await client.get(path)
            response2 = await client.get(path)

            id1 = response1.headers["x-request-id"]
            id2 = response2.headers["x-request-id"]

            assert id1 != id2
