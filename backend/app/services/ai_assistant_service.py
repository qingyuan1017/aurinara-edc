"""Optional AI assistant integration backed by Bedrock AgentCore.

The service keeps provider integration, authorization-scope filtering, and
regulated-data mutation controls in one backend boundary.  Provider payloads
never receive out-of-scope clinical context, and a suggestion cannot mutate
clinical data without a separate human confirmation signal.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar
from uuid import UUID

from app.core.audit import audit_service
from app.core.config import get_settings
from app.core.ctms import Module
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ServiceUnavailableError,
    ValidationError,
)
from app.models.form_data import FormInstance
from app.schemas.permission import AuthorizationScope
from app.services.ai_platform_service import ai_platform_service
from app.services.data_capture_service import data_capture_service
from app.services.permission_service import PermissionService
from app.services.pv_atomicity_service import pv_atomicity_service

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_DROP = object()
_RECORD_SCOPE_KEYS = (
    "study_id",
    "site_id",
    "subject_id",
    "form_instance_id",
    "visit_instance_id",
    "field_value_id",
)
_WRITE_PERMISSIONS = (
    "form.enter",
    "form.submit",
    "subject.update",
    "form.configure",
    "editcheck.configure",
)
_CTMS_WRITE_PERMISSIONS = (
    "ctms.operational-study-management",
    "ctms.operational-site-management",
    "ctms.monitoring-activity-management",
    "ctms.enrollment-management",
)
# PV-scoped write permissions. A confirmed AI-assisted change to PV Safety_Data
# requires the user to already hold one of these safety write grants at the
# target scope (Requirements 22.3, 22.4). No PV role carries an EDC clinical or
# CTMS operational mutation permission, so a PV AI change can never mutate an
# EDC clinical or CTMS operational record.
_PV_WRITE_PERMISSIONS = (
    "safety_narrative.write",
    "safety_case.enter",
    "safety_case.lifecycle",
    "safety_assessment.record",
    "safety_coding.assign",
    "safety_report.manage",
)


class AIProviderError(RuntimeError):
    """Raised when the configured AI provider cannot produce a response."""


class AIStreamProvider(Protocol):
    """Provider contract used by :class:`AIAssistantService`."""

    async def stream(
        self, operation: str, payload: Mapping[str, Any]
    ) -> AsyncIterator[str | bytes | Mapping[str, Any]]:
        """Yield response chunks for one assistant operation."""
        ...


class BedrockAgentCoreProvider:
    """Small optional adapter for the Bedrock AgentCore Runtime API.

    ``boto3`` is imported only when the provider is used, so the core API can
    run with the AI assistant disabled without adding an AWS runtime
    dependency. AgentCore's response body is synchronous, therefore the SDK
    invocation is performed in a worker thread and its returned chunks are
    normalized before being yielded to the async SSE response.
    """

    def __init__(self, runtime_arn: str, region: str | None = None) -> None:
        self.runtime_arn = runtime_arn
        self.region = region

    async def stream(
        self, operation: str, payload: Mapping[str, Any]
    ) -> AsyncIterator[str | bytes | Mapping[str, Any]]:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on deployment extras
            raise AIProviderError(
                "The Bedrock AgentCore runtime dependency is not installed"
            ) from exc

        def invoke() -> Any:
            kwargs: dict[str, Any] = {}
            if self.region:
                kwargs["region_name"] = self.region
            client = boto3.client("bedrock-agentcore-runtime", **kwargs)
            request = {"operation": operation, "input": dict(payload)}
            return client.invoke_agent_runtime(
                agentRuntimeArn=self.runtime_arn,
                payload=json.dumps(request).encode("utf-8"),
                contentType="application/json",
                accept="application/json",
            )

        try:
            response = await asyncio.to_thread(invoke)
            body = response.get("responseStream") or response.get("completion") or response
            if isinstance(body, (str, bytes, Mapping)):
                body = [body]
            for event in body:
                yield self._extract_chunk(event)
        except AIProviderError:
            raise
        except Exception as exc:  # pragma: no cover - provider/network dependent
            logger.exception("Bedrock AgentCore invocation failed")
            raise AIProviderError("The AI provider failed to generate a response") from exc

    @staticmethod
    def _extract_chunk(event: Any) -> str | bytes | Mapping[str, Any]:
        """Extract common AgentCore event shapes without exposing SDK details."""
        if isinstance(event, Mapping):
            chunk = event.get("chunk")
            if isinstance(chunk, Mapping) and "bytes" in chunk:
                return chunk["bytes"]
            for key in ("text", "outputText", "completion", "content"):
                if key in event:
                    return event[key]
        return event


class AIAssistantService:
    """Orchestrate AI operations while enforcing EDC data boundaries."""

    def __init__(
        self,
        provider: AIStreamProvider | None = None,
        permission_service: PermissionService | None = None,
        module: Module | str = Module.EDC,
    ) -> None:
        self._provider = provider
        self.permission_service = permission_service or PermissionService()
        self.module = Module(str(module).upper())

    @property
    def provider(self) -> AIStreamProvider:
        """Return an injected provider or the configured AgentCore adapter."""
        if self._provider is not None:
            return self._provider
        settings = get_settings()
        if not settings.bedrock_agentcore_runtime_arn:
            raise ServiceUnavailableError(
                message="The AI assistant is not configured",
                details={"service": "ai_assistant"},
            )
        return BedrockAgentCoreProvider(
            runtime_arn=settings.bedrock_agentcore_runtime_arn,
            region=settings.bedrock_agentcore_region,
        )

    def ensure_enabled(self) -> None:
        """Reject requests unless the optional assistant is enabled.

        EDC uses the base ``ai_assistant_enabled`` flag. CTMS and PV each carry
        an additional module flag routed through the shared platform gate so a
        module-scoped assistant can be enabled or disabled independently; when
        disabled no operation is exposed (Requirement 22.1).
        """
        if self.module in (Module.CTMS, Module.PV):
            ai_platform_service.ensure_enabled(self.module)
        elif not get_settings().ai_assistant_enabled:
            raise ServiceUnavailableError(
                message="The AI assistant is disabled",
                details={"service": "ai_assistant"},
            )
        # Resolve configuration before response headers are sent.
        _ = self.provider

    def build_context(self, user: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        """Return a provider payload containing only in-scope clinical context.

        Request fields such as ``message`` and ``prompt`` are retained, but
        mappings/lists carrying ``study_id`` or ``site_id`` are treated as
        clinical records and filtered against the user's resolved
        Authorization_Scope. An explicitly requested out-of-scope target is
        rejected rather than silently rewritten. This makes a caller unable to
        use the model as a side channel for data outside its scope.
        """
        if not isinstance(request, Mapping):
            raise ValidationError("AI request must be an object")

        scope = self._resolve_scope(user)
        top_level_study = request.get("study_id")
        top_level_site = request.get("site_id")
        has_unresolvable_target = any(
            request.get(key) is not None for key in _RECORD_SCOPE_KEYS[2:]
        )
        if (
            has_unresolvable_target
            and top_level_study is None
            and top_level_site is None
            and not scope.has_system_grant()
        ):
            raise AuthorizationError(
                    message="AI request does not identify an authorization-scoped target",
                    details={"required": "study_id and optional site_id"},
                )
        if (top_level_study is not None or top_level_site is not None) and not self._scope_allows(
            scope, top_level_study, top_level_site
        ):
            raise AuthorizationError(
                message="AI request is outside the user's authorization scope",
                details={
                    "study_id": str(top_level_study) if top_level_study is not None else None,
                    "site_id": str(top_level_site) if top_level_site is not None else None,
                },
            )

        filtered: dict[str, Any] = {}
        for key, value in request.items():
            result = self._filter_context_value(value, scope)
            if result is not _DROP:
                filtered[str(key)] = result
        return ai_platform_service.minimize_context(filtered, module=self.module)

    async def apply_suggestion(
        self,
        suggestion: Mapping[str, Any],
        *,
        user: Any | None = None,
        session: Any | None = None,
        confirmed: bool = False,
        target_object: Any | None = None,
        apply_change: Callable[[Mapping[str, Any]], _T | Awaitable[_T]] | None = None,
    ) -> dict[str, Any]:
        """Apply a suggestion only after explicit human confirmation.

        A suggestion is considered data-changing when it contains a non-empty
        ``changes`` or ``data_changes`` collection. Such a suggestion cannot
        proceed based on a flag embedded in model output; the caller must pass
        the independent ``confirmed=True`` signal. The target must be in the
        user's scope and the caller must hold an existing clinical write grant.
        The actual change and its AI audit event use the same session.
        """
        if not isinstance(suggestion, Mapping):
            raise ValidationError("AI suggestion must be an object")

        changes = suggestion.get("data_changes")
        if changes is None:
            changes = suggestion.get("changes")
        is_data_change = bool(changes) or bool(
            suggestion.get("would_change_data") or suggestion.get("data_change")
        )
        if not is_data_change:
            return {"status": "preview", "suggestion": dict(suggestion)}

        if not confirmed:
            raise ValidationError(
                message="Explicit human confirmation is required before applying an AI data change",
                details={"requires_confirmation": True},
            )
        if user is None:
            raise AuthenticationError(
                message="An authenticated user is required to apply an AI data change"
            )
        if session is None:
            raise ValidationError(
                message="A database session is required to apply an AI data change",
                details={"requires_transaction": True},
            )

        target = target_object or suggestion.get("target") or suggestion.get("object") or suggestion
        target_details = self._target_details(target, suggestion)
        study_id = target_details["study_id"]
        site_id = target_details["site_id"]
        if not self._scope_allows(self._resolve_scope(user), study_id, site_id):
            raise AuthorizationError(
                message="AI suggestion target is outside the user's authorization scope",
                details={
                    "study_id": str(study_id) if study_id is not None else None,
                    "site_id": str(site_id) if site_id is not None else None,
                },
            )
        self._require_write_scope(user, study_id, site_id)

        # CTMS and PV never mutate their authoritative records through the AI
        # boundary directly; the owning module supplies the confirmed-change
        # callback so the AI platform holds no mutation authority for those
        # modules (Requirements 22.4, 23.4, 23.5).
        if self.module in (Module.CTMS, Module.PV) and apply_change is None:
            raise ValidationError(
                message=(
                    f"The AI platform cannot mutate {self.module.value} records "
                    "without an owning-service callback"
                ),
                details={"module": self.module.value, "requires_owner_service": True},
            )

        if apply_change is not None:
            result = apply_change(suggestion)
            if inspect.isawaitable(result):
                result = await result
        else:
            result = await self._apply_form_changes(
                session,
                target,
                changes,
                actor_id=self._user_id(user),
                reason=str(
                    suggestion.get("reason")
                    or "AI-assisted change explicitly confirmed by a human"
                ),
            )

        entity_id = target_details["entity_id"]
        if entity_id is None:
            raise ValidationError(
                message="AI suggestion target must identify a persisted object",
                details={"required": "target.id or target_id"},
            )
        reason = str(
            suggestion.get("reason")
            or "AI-assisted change explicitly confirmed by a human"
        )
        if self.module is Module.PV:
            # Record exactly one PV safety Audit_Event (module="PV") identifying
            # the user, the changed safety object, the action, and the
            # AI-assisted origin, on the caller's transaction so the confirmed
            # change and its audit event commit or roll back together
            # (Requirements 22.5, 11.7, 18.3).
            await pv_atomicity_service.record_mutation(
                session,
                entity_type=target_details["entity_type"],
                entity_id=entity_id,
                action="ai_assisted_change",
                actor_id=self._user_id(user),
                study_id=study_id,
                site_id=site_id,
                subject_id=target_details["subject_id"],
                changed_fields=tuple(changes) if isinstance(changes, Mapping) else (),
                reason=reason,
                new_value="ai_assisted",
            )
        else:
            await audit_service.record(
                session,
                entity_type=target_details["entity_type"],
                entity_id=entity_id,
                action="ai_assisted_change",
                study_id=study_id,
                site_id=site_id,
                subject_id=target_details["subject_id"],
                reason=reason,
                actor_id=self._user_id(user),
                new_value=json.dumps(changes, default=str, sort_keys=True),
            )
        return {"status": "applied", "suggestion": dict(suggestion), "result": result}

    def stream(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        user_id: Any,
        user: Any | None = None,
    ) -> AsyncIterator[str]:
        """Return an async SSE event stream for one supported operation.

        ``user`` is supplied by authenticated routes so context is scoped. The
        ``user_id``-only form remains supported for callers that send no
        clinical context and preserves task 31.1 compatibility.
        """
        self.ensure_enabled()
        scoped_payload = self.build_context(user, payload) if user is not None else dict(payload)
        return self._stream(operation, scoped_payload, user_id=user_id)

    async def _stream(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        user_id: Any,
    ) -> AsyncIterator[str]:
        request = {
            "user_id": str(user_id),
            "operation": operation,
            "payload": dict(payload),
        }
        try:
            async for chunk in self.provider.stream(operation, request):
                text = self._chunk_text(chunk)
                if text:
                    yield self._event({"type": "token", "content": text})
            yield self._event({"type": "done"})
        except AIProviderError as exc:
            logger.warning("AI provider error during %s: %s", operation, exc)
            yield self._event(
                {"type": "error", "code": "AIProviderError", "message": str(exc)},
                event="error",
            )

    def _resolve_scope(self, user: Any) -> AuthorizationScope:
        """Resolve a User's Authorization_Scope through Permission_Service."""
        if user is None:
            return AuthorizationScope(grants=[])
        explicit_scope = getattr(user, "authorization_scope", None)
        if isinstance(explicit_scope, AuthorizationScope):
            return explicit_scope
        # Lightweight callers (for example stream adapters) may carry only an
        # identity and no ORM role relationship. They have no clinical scope.
        if not hasattr(user, "user_roles"):
            return AuthorizationScope(grants=[])
        return self.permission_service.resolve_scope(user)

    @staticmethod
    def _scope_allows(
        scope: AuthorizationScope,
        study_id: Any | None,
        site_id: Any | None,
    ) -> bool:
        """Check scope using any grant, independent of operation permission."""
        if study_id is None and site_id is None:
            return scope.has_system_grant()
        study = AIAssistantService._normalized_id(study_id)
        site = AIAssistantService._normalized_id(site_id)
        for grant in scope.grants:
            grant_study = AIAssistantService._normalized_id(grant.study_id)
            grant_site = AIAssistantService._normalized_id(grant.site_id)
            if grant_study is None and grant_site is None:
                return True
            if study is not None and grant_study == study and grant_site is None:
                return True
            if study is not None and site is not None and grant_study == study and grant_site == site:
                return True
        return False

    def _require_write_scope(self, user: Any, study_id: Any, site_id: Any) -> None:
        scope = self._resolve_scope(user)
        if self.module is Module.CTMS:
            permissions = _CTMS_WRITE_PERMISSIONS
        elif self.module is Module.PV:
            permissions = _PV_WRITE_PERMISSIONS
        else:
            permissions = _WRITE_PERMISSIONS
        if not any(scope.has_permission(permission, study_id=study_id, site_id=site_id) for permission in permissions):
            raise AuthorizationError(
                message="The user lacks a module write permission for the AI suggestion target",
                details={
                    "module": self.module.value,
                    "study_id": str(study_id),
                    "site_id": str(site_id) if site_id else None,
                },
            )

    @classmethod
    def _filter_context_value(cls, value: Any, scope: AuthorizationScope) -> Any:
        """Recursively filter scoped records while retaining request text."""
        if isinstance(value, Mapping):
            study_id = value.get("study_id")
            site_id = value.get("site_id")
            has_unresolvable_scope = (
                (study_id is None and site_id is None)
                and any(value.get(key) is not None for key in _RECORD_SCOPE_KEYS[2:])
            )
            if has_unresolvable_scope and not scope.has_system_grant():
                return _DROP
            if (study_id is not None or site_id is not None) and not cls._scope_allows(
                scope, study_id, site_id
            ):
                return _DROP
            filtered: dict[str, Any] = {}
            for key, nested in value.items():
                if key in {"study_ids", "site_ids"} and isinstance(nested, list):
                    filtered[str(key)] = [
                        item
                        for item in nested
                        if cls._scope_allows(
                            scope,
                            item if key == "study_ids" else None,
                            item if key == "site_ids" else None,
                        )
                    ]
                    continue
                result = cls._filter_context_value(nested, scope)
                if result is not _DROP:
                    filtered[str(key)] = result
            return filtered
        if isinstance(value, list):
            return [
                result
                for item in value
                if (result := cls._filter_context_value(item, scope)) is not _DROP
            ]
        if isinstance(value, tuple):
            return tuple(
                result
                for item in value
                if (result := cls._filter_context_value(item, scope)) is not _DROP
            )
        return value

    async def _apply_form_changes(
        self,
        session: Any,
        target: Any,
        changes: Any,
        *,
        actor_id: UUID,
        reason: str,
    ) -> Any:
        """Apply the supported clinical form suggestion through Data_Capture."""
        if not isinstance(target, FormInstance):
            raise ValidationError(
                message="AI suggestion target type is not supported for data changes",
                details={"supported_target": "form_instance"},
            )
        entries = changes.items() if isinstance(changes, Mapping) else changes
        result = target
        for entry in entries:
            if isinstance(changes, Mapping):
                field_id, new_value = entry
            else:
                if not isinstance(entry, Mapping):
                    raise ValidationError("Each AI form change must be an object")
                field_id = entry.get("field_id") or entry.get("field_definition_id")
                new_value = entry.get("value")
            if field_id is None:
                raise ValidationError("Each AI form change requires a field_id")
            result = await data_capture_service.change_value(
                session,
                target,
                UUID(str(field_id)),
                new_value,
                reason,
                actor_id,
            )
        return result

    @classmethod
    def _target_details(cls, target: Any, suggestion: Mapping[str, Any]) -> dict[str, Any]:
        def get(name: str) -> Any:
            if isinstance(target, Mapping) and target.get(name) is not None:
                return target.get(name)
            value = getattr(target, name, None)
            if value is not None:
                return value
            return suggestion.get(name)

        subject = getattr(target, "subject", None)
        site = getattr(subject, "site", None)
        study = getattr(subject, "study", None)
        study_id = get("study_id") or getattr(study, "id", None)
        site_id = get("site_id") or getattr(site, "id", None)
        subject_id = get("subject_id") or getattr(subject, "id", None)
        entity_id = get("id") or suggestion.get("target_id")
        return {
            "entity_type": str(get("entity_type") or suggestion.get("target_type") or "clinical_data"),
            "entity_id": cls._as_uuid(entity_id),
            "study_id": cls._as_uuid(study_id),
            "site_id": cls._as_uuid(site_id),
            "subject_id": cls._as_uuid(subject_id),
        }

    @staticmethod
    def _as_uuid(value: Any | None) -> UUID | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _normalized_id(value: Any | None) -> str | None:
        if value is None:
            return None
        return str(value).lower()

    @staticmethod
    def _user_id(user: Any) -> UUID:
        user_id = AIAssistantService._as_uuid(getattr(user, "id", None))
        if user_id is None:
            raise AuthenticationError("Authenticated user has no valid identity")
        return user_id

    @staticmethod
    def _chunk_text(chunk: str | bytes | Mapping[str, Any]) -> str:
        if isinstance(chunk, bytes):
            return chunk.decode("utf-8", errors="replace")
        if isinstance(chunk, str):
            return chunk
        return str(
            chunk.get("text")
            or chunk.get("outputText")
            or chunk.get("content")
            or chunk
        )

    @staticmethod
    def _event(data: Mapping[str, Any], *, event: str | None = None) -> str:
        prefix = f"event: {event}\n" if event else ""
        return f"{prefix}data: {json.dumps(dict(data), ensure_ascii=False)}\n\n"


ai_assistant_service = AIAssistantService()
# PV-scoped assistant. It reuses the same provider transport and shared controls
# but is bound to the PV module so enablement (``pv_ai_enabled``), context
# minimization, write-permission checks, and audit content are all PV-scoped.
pv_ai_assistant_service = AIAssistantService(module=Module.PV)

__all__ = [
    "AIAssistantService",
    "AIProviderError",
    "AIStreamProvider",
    "BedrockAgentCoreProvider",
    "ai_assistant_service",
    "pv_ai_assistant_service",
]
