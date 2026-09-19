"""Request-ID middleware.

Assigns a UUID request identifier at ingress (or accepts one from the
incoming X-Request-ID header), binds it to contextvars for log correlation
and audit propagation, and returns it in the X-Request-ID response header.

Satisfies Requirements 21.5 and 30.4.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.observability import sanitize_error
from app.core.request_context import (
    actor_var,
    correlation_id_var,
    request_id_var,
    trace_id_var,
)

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that manages request_id lifecycle via contextvars."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept bounded client-provided identifiers or generate new UUID4 values.
        # Bounded values prevent untrusted headers from becoming log/header injection.
        incoming_id = request.headers.get("X-Request-ID", "").strip()
        incoming_correlation_id = request.headers.get("X-Correlation-ID", "").strip()
        incoming_trace_id = request.headers.get("X-Trace-ID", "").strip()
        req_id = incoming_id[:128] if incoming_id else str(uuid.uuid4())
        correlation_id = (
            incoming_correlation_id[:128] if incoming_correlation_id else str(uuid.uuid4())
        )
        trace_id = incoming_trace_id[:128] if incoming_trace_id else str(uuid.uuid4())

        request.state.request_id = req_id
        request.state.correlation_id = correlation_id
        request.state.trace_id = trace_id

        # Bind to contextvars for the duration of this request.
        token_req = request_id_var.set(req_id)
        token_correlation = correlation_id_var.set(correlation_id)
        token_trace = trace_id_var.set(trace_id)
        token_actor = actor_var.set(None)  # Auth dependency sets it later.

        start_time = time.perf_counter()
        status_code = 500  # Default in case of unhandled exception

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            logger.error(
                "Unhandled exception during request processing: category=%s",
                sanitize_error(exc)["category"],
            )
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "Request completed: %s %s -> %d (%.1fms)",
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )
            # Reset contextvars
            request_id_var.reset(token_req)
            correlation_id_var.reset(token_correlation)
            trace_id_var.reset(token_trace)
            actor_var.reset(token_actor)

        # Propagate both identifiers on every normal response.
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Trace-ID"] = trace_id
        return response
