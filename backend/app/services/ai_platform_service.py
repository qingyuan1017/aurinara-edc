"""Shared optional AI controls for the EDC and CTMS modules.

This service is deliberately an authorization and safety hook, not a business
service.  It never writes module records.  The owning module must provide the
confirmed action callback and audit sink.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from app.core.config import get_settings
from app.core.ctms import Module
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.observability import sanitize_fields
from app.schemas.permission import AuthorizationScope

_T = TypeVar("_T")

# These fields are never sent to a model, regardless of module.
_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "field_values",
        "clinical_data",
        "source_documents",
        "clinical_notes",
        "query_messages",
        "raw_event_body",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


class AIPlatformService:
    """Apply shared module scope, minimization, confirmation, and audit hooks."""

    def ensure_enabled(self, module: Module | str) -> None:
        """Reject disabled AI or CTMS AI without changing module state."""
        settings = get_settings()
        normalized = Module(str(module).upper())
        if not settings.ai_assistant_enabled or (
            normalized is Module.CTMS and not settings.ctms_ai_enabled
        ):
            raise ServiceUnavailableError(
                message="The optional AI capability is disabled",
                details={"module": normalized.value, "service": "ai_platform"},
            )

    @classmethod
    def minimize_context(cls, context: Any, *, module: Module | str) -> Any:
        """Return a recursively minimized, non-sensitive model context."""
        normalized = Module(str(module).upper())
        if isinstance(context, Mapping):
            result: dict[str, Any] = {}
            for raw_key, value in context.items():
                key = str(raw_key)
                key_normalized = key.lower()
                if key_normalized in _FORBIDDEN_CONTEXT_KEYS:
                    continue
                # CTMS AI receives operational context only; clinical payloads
                # are excluded by semantic key, not merely by authorization.
                if normalized is Module.CTMS and (
                    key_normalized.startswith("clinical_")
                    or key_normalized in {"field_values", "form_values", "source_data"}
                ):
                    continue
                result[key] = cls.minimize_context(value, module=normalized)
            return sanitize_fields(result)
        if isinstance(context, (list, tuple)):
            return [cls.minimize_context(item, module=normalized) for item in context]
        return context

    @staticmethod
    def require_scope(
        scope: AuthorizationScope,
        *,
        permission: str,
        study_id: Any | None,
        site_id: Any | None,
    ) -> None:
        """Require one existing server-side permission at the target scope."""
        if not scope.has_permission(permission, study_id=study_id, site_id=site_id):
            raise AuthorizationError(
                message="AI action is outside the user's authorization scope",
                details={"permission": permission, "study_id": str(study_id) if study_id else None, "site_id": str(site_id) if site_id else None},
            )

    async def apply_confirmed_action(
        self,
        *,
        module: Module | str,
        scope: AuthorizationScope,
        permission: str,
        study_id: Any | None,
        site_id: Any | None,
        confirmed: bool,
        actor: Any | None,
        action: Mapping[str, Any],
        apply_change: Callable[[Mapping[str, Any]], _T | Awaitable[_T]],
        audit: Callable[[dict[str, Any]], Any | Awaitable[Any]],
    ) -> dict[str, Any]:
        """Audit and apply an owning-module action after human confirmation.

        ``apply_change`` is supplied by the owning module.  Without that
        callback this shared service has no mutation authority.
        """
        normalized = Module(str(module).upper())
        self.ensure_enabled(normalized)
        if actor is None:
            raise AuthenticationError(message="An authenticated user is required for an AI action")
        if not confirmed:
            raise ValidationError(
                message="Explicit human confirmation is required before applying an AI action",
                details={"requires_confirmation": True},
            )
        self.require_scope(
            scope,
            permission=permission,
            study_id=study_id,
            site_id=site_id,
        )
        if not isinstance(action, Mapping):
            raise ValidationError(message="AI action must be an object")

        audit_record = {
            "module": normalized.value,
            "action": "ai_action_confirmed",
            "actor_id": str(getattr(actor, "id", actor)),
            "study_id": str(study_id) if study_id is not None else None,
            "site_id": str(site_id) if site_id is not None else None,
        }
        audit_result = audit(sanitize_fields(audit_record))
        if inspect.isawaitable(audit_result):
            await audit_result

        result = apply_change(action)
        if inspect.isawaitable(result):
            result = await result
        return {"status": "applied", "module": normalized.value, "result": result}


ai_platform_service = AIPlatformService()

__all__ = ["AIPlatformService", "ai_platform_service"]
