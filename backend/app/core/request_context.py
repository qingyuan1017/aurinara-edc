"""Request-scoped context variables.

Provides contextvars for request_id and actor (authenticated user identity)
so that any code in the call stack can access them without explicit parameter
passing. Used by the audit subsystem and structured logging to correlate
every log line and Audit_Event with the originating request.

Satisfies Requirements 21.5 and 30.4.
"""

from contextvars import ContextVar
from uuid import UUID

# Unique identifier assigned at request ingress (or accepted from X-Request-ID header).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Authenticated actor identifier (User UUID) bound after auth resolution.
actor_var: ContextVar[UUID | None] = ContextVar("actor", default=None)


def get_request_id() -> str | None:
    """Return the current request identifier, or None outside a request."""
    return request_id_var.get()


def get_actor() -> UUID | None:
    """Return the current actor (user id), or None if unauthenticated."""
    return actor_var.get()
