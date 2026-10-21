"""Client for the independently deployed Aurinara authorization control plane."""

from __future__ import annotations

import logging
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError
from app.core.permissions import platform_permission_code
from app.models.shared.identity import User
from app.schemas.shared.permission import normalize_permission_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlatformDecision:
    allowed: bool
    decision_id: UUID
    policy_version: int
    expires_at: datetime
    reason_code: str


class AuthorizationGateway(Protocol):
    mode: str

    def decide(
        self,
        user: User,
        permission: str,
        *,
        study_id: UUID | None,
        site_id: UUID | None,
    ) -> PlatformDecision: ...


_decision_context: ContextVar[PlatformDecision | None] = ContextVar(
    "platform_authorization_decision", default=None
)


def get_authorization_decision() -> PlatformDecision | None:
    """Return the central decision attached to the current execution context."""

    return _decision_context.get()


def namespaced_permission(permission: str) -> str:
    """Map legacy permission codes to the stable control-plane namespace."""

    permission = normalize_permission_code(permission)
    return platform_permission_code(permission)


class PlatformAuthorizationClient:
    """Synchronous PDP client with a bounded positive-decision cache."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.mode = settings.platform_authorization_mode
        self._base_url = (settings.platform_control_plane_url or "").rstrip("/")
        self._issuer = settings.platform_identity_issuer or settings.auth_issuer or ""
        self._token_url = settings.platform_service_token_url
        self._client_id = settings.platform_service_client_id
        self._client_secret = settings.platform_service_client_secret
        self._audience = settings.platform_service_audience
        self._scope = settings.platform_service_scope
        self._resource = settings.platform_service_resource
        self._max_cache_seconds = settings.platform_authorization_cache_seconds
        self._client = httpx.Client(
            transport=transport, timeout=settings.platform_authorization_timeout_seconds
        )
        self._lock = threading.Lock()
        self._token: tuple[str, float] | None = None
        self._cache: dict[tuple[object, ...], tuple[PlatformDecision, float]] = {}

    def decide(
        self,
        user: User,
        permission: str,
        *,
        study_id: UUID | None,
        site_id: UUID | None,
    ) -> PlatformDecision:
        if not self._base_url:
            raise ServiceUnavailableError("Platform authorization is not configured")
        subject = user.external_subject or str(user.id)
        issuer = user.external_issuer or self._issuer
        if not issuer:
            raise ServiceUnavailableError("Platform identity issuer is not configured")
        action = namespaced_permission(permission)
        key = (issuer, subject, action, study_id, site_id)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[1] > now:
            _decision_context.set(cached[0])
            return cached[0]
        try:
            response = self._client.post(
                f"{self._base_url}/v1/authorization/decisions",
                headers={"Authorization": f"Bearer {self.service_token()}"},
                json={
                    "principal": {"issuer": issuer, "subject": subject},
                    "action": action,
                    "resource": {
                        "product": "aurinara-edc",
                        "type": "permission_scope",
                        "study_id": str(study_id) if study_id else None,
                        "site_id": str(site_id) if site_id else None,
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
            decision = PlatformDecision(
                allowed=bool(payload["allowed"]),
                decision_id=UUID(payload["decision_id"]),
                policy_version=int(payload["policy_version"]),
                expires_at=datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")),
                reason_code=str(payload["reason_code"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            cached = self._cache.get(key)
            if cached is not None and cached[1] > time.monotonic():
                _decision_context.set(cached[0])
                return cached[0]
            raise ServiceUnavailableError(
                "Platform authorization is temporarily unavailable"
            ) from error
        _decision_context.set(decision)
        if decision.allowed and self._max_cache_seconds:
            ttl = min(
                self._max_cache_seconds,
                max(0.0, decision.expires_at.timestamp() - time.time()),
            )
            self._cache[key] = (decision, time.monotonic() + ttl)
        return decision

    def decide_batch(
        self,
        user: User,
        permission: str,
        resources: tuple[tuple[UUID | None, UUID | None], ...],
    ) -> tuple[PlatformDecision, ...]:
        """Resolve multiple study/site scopes in one PDP request."""

        if not resources:
            return ()
        if not self._base_url:
            raise ServiceUnavailableError("Platform authorization is not configured")
        subject = user.external_subject or str(user.id)
        issuer = user.external_issuer or self._issuer
        if not issuer:
            raise ServiceUnavailableError("Platform identity issuer is not configured")
        action = namespaced_permission(permission)
        now = time.monotonic()
        resolved: dict[tuple[UUID | None, UUID | None], PlatformDecision] = {}
        missing: list[tuple[UUID | None, UUID | None]] = []
        for study_id, site_id in resources:
            cached = self._cache.get((issuer, subject, action, study_id, site_id))
            if cached is not None and cached[1] > now:
                resolved[(study_id, site_id)] = cached[0]
            else:
                missing.append((study_id, site_id))
        if missing:
            try:
                response = self._client.post(
                    f"{self._base_url}/v1/authorization/decisions:batch",
                    headers={"Authorization": f"Bearer {self.service_token()}"},
                    json={
                        "decisions": [
                            {
                                "principal": {"issuer": issuer, "subject": subject},
                                "action": action,
                                "resource": {
                                    "product": "aurinara-edc",
                                    "type": "permission_scope",
                                    "study_id": str(study_id) if study_id else None,
                                    "site_id": str(site_id) if site_id else None,
                                },
                            }
                            for study_id, site_id in missing
                        ]
                    },
                )
                response.raise_for_status()
                payloads = response.json()["decisions"]
                if len(payloads) != len(missing):
                    raise ValueError("authorization batch response length mismatch")
                for resource, payload in zip(missing, payloads, strict=True):
                    decision = PlatformDecision(
                        allowed=bool(payload["allowed"]),
                        decision_id=UUID(payload["decision_id"]),
                        policy_version=int(payload["policy_version"]),
                        expires_at=datetime.fromisoformat(
                            payload["expires_at"].replace("Z", "+00:00")
                        ),
                        reason_code=str(payload["reason_code"]),
                    )
                    resolved[resource] = decision
                    if decision.allowed and self._max_cache_seconds:
                        ttl = min(
                            self._max_cache_seconds,
                            max(0.0, decision.expires_at.timestamp() - time.time()),
                        )
                        self._cache[(issuer, subject, action, *resource)] = (
                            decision,
                            time.monotonic() + ttl,
                        )
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                raise ServiceUnavailableError(
                    "Platform authorization is temporarily unavailable"
                ) from error
        decisions = tuple(resolved[resource] for resource in resources)
        if decisions:
            _decision_context.set(decisions[-1])
        return decisions

    def service_token(self) -> str:
        """Return a cached client-credentials token for control-plane calls."""
        now = time.monotonic()
        if self._token is not None and self._token[1] > now:
            return self._token[0]
        if not self._token_url or not self._client_id or self._client_secret is None:
            raise ServiceUnavailableError("Platform service credentials are not configured")
        try:
            token_command = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret.get_secret_value(),
                "audience": self._audience,
                "scope": self._scope,
            }
            if self._resource:
                token_command["resource"] = self._resource
            response = self._client.post(self._token_url, data=token_command)
            response.raise_for_status()
            payload = response.json()
            token = str(payload["access_token"])
            expires_in = max(30, int(payload.get("expires_in", 300)))
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform service authentication is temporarily unavailable"
            ) from error
        with self._lock:
            self._token = (token, time.monotonic() + expires_in - 15)
        return token

    def sync_permissions(self, permissions: list[dict[str, object]]) -> tuple[str, ...]:
        """Register the EDC-owned capability catalog without defining roles."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform authorization is not configured")
        try:
            response = self._client.put(
                f"{self._base_url}/v1/products/aurinara-edc/permissions",
                headers={"Authorization": f"Bearer {self.service_token()}"},
                json={"permissions": permissions},
            )
            response.raise_for_status()
            payload = response.json()
            return tuple(str(item["code"]) for item in payload)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform permission registration is temporarily unavailable"
            ) from error

    def sync_site(
        self,
        *,
        study_id: UUID,
        site_id: UUID,
        name: str,
        country: str | None,
        state: str | None,
        city: str | None,
        status: str = "active",
    ) -> None:
        """Register a CTMS-created canonical Site with the control plane."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform authorization is not configured")
        try:
            response = self._client.put(
                f"{self._base_url}/v1/products/aurinara-edc/studies/{study_id}/sites/{site_id}",
                headers={"Authorization": f"Bearer {self.service_token()}"},
                json={
                    "name": name,
                    "country": country,
                    "state": state,
                    "city": city,
                    "status": status,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if UUID(payload["id"]) != site_id or UUID(payload["study_id"]) != study_id:
                raise ValueError("platform returned a different canonical Site identity")
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform Site registration is temporarily unavailable"
            ) from error

    def invalidate(self, *, study_id: UUID | None = None) -> None:
        """Invalidate cached allows after a membership, policy, or user event."""

        with self._lock:
            if study_id is None:
                self._cache.clear()
            else:
                self._cache = {
                    key: value for key, value in self._cache.items() if key[3] != study_id
                }


_gateway: PlatformAuthorizationClient | None = None


def get_platform_authorization() -> PlatformAuthorizationClient:
    global _gateway
    if _gateway is None:
        _gateway = PlatformAuthorizationClient(get_settings())
    return _gateway


def reset_platform_authorization() -> None:
    """Reset the singleton after a settings override in tests."""

    global _gateway
    _gateway = None
