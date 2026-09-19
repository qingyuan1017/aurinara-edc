"""Request-scoped identifiers and authenticated actor context.

The request context is deliberately small and transport-independent so routes,
services, audit records, and structured logs can all use the same values. The
middleware owns request/correlation lifecycle; authentication binds the actor.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
actor_var: ContextVar[UUID | None] = ContextVar("actor", default=None)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Immutable snapshot of the current request's trace and actor metadata."""

    request_id: str | None
    correlation_id: str | None
    trace_id: str | None
    actor_id: UUID | None


def get_request_id() -> str | None:
    """Return the current request identifier, or ``None`` outside a request."""

    return request_id_var.get()


def get_correlation_id() -> str | None:
    """Return the current correlation identifier, or ``None`` outside a request."""

    return correlation_id_var.get()


def get_trace_id() -> str | None:
    """Return the current distributed trace identifier, if present."""

    return trace_id_var.get()


def get_actor() -> UUID | None:
    """Return the authenticated actor identifier, if one has been resolved."""

    return actor_var.get()


def set_actor(actor_id: UUID | None) -> None:
    """Bind an authenticated actor to the current request context."""

    actor_var.set(actor_id)


def get_request_context() -> RequestContext:
    """Return a point-in-time snapshot of request and actor context."""

    return RequestContext(
        request_id=get_request_id(),
        correlation_id=get_correlation_id(),
        trace_id=get_trace_id(),
        actor_id=get_actor(),
    )
