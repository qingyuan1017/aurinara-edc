"""Property-based test for the standard error envelope.

**Validates: Requirements 21.3**

Property 33: Error envelope is standard and leak-free.

Generates arbitrary domain exceptions and unexpected RuntimeErrors, then asserts:
1. Domain exceptions always produce the standard envelope structure.
2. Unexpected exceptions (500) never leak internal details.
3. RuntimeError messages never appear verbatim in the response body.
"""

import re
from typing import Any

import pytest
from fastapi import FastAPI
from hypothesis import given, settings
from hypothesis import strategies as st
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary messages including potentially dangerous content
_internal_leak_patterns = st.sampled_from(
    [
        "DB connection lost: host=10.0.0.5 port=5432",
        "psycopg2.OperationalError: FATAL: password authentication failed",
        "sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint",
        "Traceback (most recent call last):\n  File '/app/services/study.py', line 42",
        "redis.exceptions.ConnectionError: Error 111 connecting to redis:6379",
        "SECRET_KEY=abc123supersecret",
        "postgresql://admin:p4ssw0rd@db.internal:5432/edc_prod",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "Connection refused: /var/run/postgresql/.s.PGSQL.5432",
    ]
)

_random_messages = st.text(min_size=1, max_size=200)

_exception_messages = st.one_of(_random_messages, _internal_leak_patterns)

# Generate arbitrary detail dicts (string keys, JSON-serializable values)
_detail_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=50),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=3),
    ),
    max_leaves=5,
)

_detail_dicts = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=_detail_values,
    max_size=5,
)

# Domain exception types and their expected HTTP status codes
_DOMAIN_EXCEPTIONS = [
    (NotFoundError, 404),
    (ValidationError, 422),
    (AuthenticationError, 401),
    (AuthorizationError, 403),
    (ConflictError, 409),
    (BusinessRuleError, 400),
]

_domain_exception_strategy = st.tuples(
    st.sampled_from(_DOMAIN_EXCEPTIONS),
    _exception_messages,
    _detail_dicts,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _create_domain_app(exc_class: type, message: str, details: dict[str, Any]) -> FastAPI:
    """Create a minimal FastAPI app that raises the given domain exception."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/trigger")
    async def trigger():
        raise exc_class(message=message, details=details)

    return app


def _create_unexpected_app(message: str) -> FastAPI:
    """Create a minimal FastAPI app that raises a RuntimeError."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/trigger")
    async def trigger():
        raise RuntimeError(message)

    return app


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@settings(max_examples=100)
@given(data=_domain_exception_strategy)
async def test_domain_exception_envelope_structure(data):
    """Property: Domain exceptions ALWAYS produce the standard envelope structure.

    **Validates: Requirements 21.3**

    For any domain exception type, message, and details dict, the response
    must contain exactly {error: {code: str, message: str, details: dict}}.
    """
    (exc_class, expected_status), message, details = data

    app = _create_domain_app(exc_class, message, details)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger")

    # Correct status code
    assert response.status_code == expected_status

    body = response.json()

    # Standard envelope structure
    assert "error" in body, "Response must have 'error' key"
    error = body["error"]
    assert isinstance(error, dict), "'error' must be a dict"
    assert "code" in error, "Envelope must have 'code'"
    assert "message" in error, "Envelope must have 'message'"
    assert "details" in error, "Envelope must have 'details'"

    # Type checks
    assert isinstance(error["code"], str), "'code' must be a string"
    assert isinstance(error["message"], str), "'message' must be a string"
    assert isinstance(error["details"], dict), "'details' must be a dict"

    # Code matches the exception class name
    assert error["code"] == exc_class.__name__


@pytest.mark.asyncio
@settings(max_examples=100)
@given(message=_exception_messages)
async def test_unexpected_exception_never_leaks_internals(message):
    """Property: Unexpected exceptions NEVER leak internal details in 500 responses.

    **Validates: Requirements 21.3**

    For any RuntimeError with arbitrary message content (including DB connection
    strings, stack traces, secrets), the 500 response must:
    - Follow the standard envelope structure
    - Use a generic error message
    - Have empty details
    - NOT contain the original exception message in the response body
    """
    app = _create_unexpected_app(message)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger")

    # Must be 500
    assert response.status_code == 500

    body = response.json()

    # Standard envelope structure
    assert "error" in body
    error = body["error"]
    assert isinstance(error, dict)
    assert "code" in error
    assert "message" in error
    assert "details" in error

    # Type checks
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], dict)

    # Generic safe code and message
    assert error["code"] == "InternalServerError"
    assert error["message"] == "An unexpected error occurred"
    assert error["details"] == {}

    # The original exception message must NOT leak into the response body
    response_text = response.text
    # Only check for non-trivial messages (single chars might appear in boilerplate)
    if len(message) > 10:
        assert message not in response_text, (
            f"Internal exception message leaked into response: {message!r}"
        )

    # Sensitive patterns must never appear in any 500 response
    _sensitive_patterns = [
        r"password",
        r"SECRET_KEY",
        r"AWS_SECRET",
        r"postgresql://\w+:\w+@",
        r"Traceback \(most recent call last\)",
        r"host=\d+\.\d+\.\d+\.\d+",
    ]
    for pattern in _sensitive_patterns:
        assert not re.search(pattern, response_text, re.IGNORECASE), (
            f"Sensitive pattern '{pattern}' found in 500 response body"
        )
