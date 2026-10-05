"""Shared helpers for PV/Safety route handlers.

These helpers keep every PV route handler thin: they build the request-scoped
actor context from the shared request middleware so PV services, audit events,
logs, and coordination records all share one request and correlation identifier.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.pv import ActorContext
from app.core.request_context import get_correlation_id, get_request_id
from app.models.identity import User


def build_actor(current_user: User) -> ActorContext:
    """Return the request-scoped :class:`ActorContext` for the current user.

    The request and correlation identifiers come from the shared request
    middleware; they fall back to a generated value only outside a request so a
    service call always carries a stable correlation identifier for audit.
    """

    return ActorContext(
        user_id=current_user.id,
        request_id=get_request_id() or str(uuid4()),
        correlation_id=get_correlation_id() or str(uuid4()),
    )


__all__ = ["build_actor"]
