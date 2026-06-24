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

from app.core.request_context import actor_var, request_id_var

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that manages request_id lifecycle via contextvars."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept client-provided request ID or generate a new one
        incoming_id = request.headers.get("X-Request-ID")
        req_id = incoming_id if incoming_id else str(uuid.uuid4())

        # Bind to contextvars for the duration of this request
        token_req = request_id_var.set(req_id)
        token_actor = actor_var.set(None)  # Reset actor; auth dependency sets it later

        start_time = time.perf_counter()
        status_code = 500  # Default in case of unhandled exception

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception("Unhandled exception during request processing")
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
            actor_var.reset(token_actor)

        # Propagate request_id in the response header
        response.headers["X-Request-ID"] = req_id
        return response
