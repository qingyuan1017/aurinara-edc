"""Client for opaque objects served by the shared platform gateway."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError
from app.services.shared.platform_authorization import (
    PlatformAuthorizationClient,
    get_platform_authorization,
)


@dataclass(frozen=True, slots=True)
class PlatformObjectRegistration:
    object_id: UUID
    reference_id: UUID


@dataclass(frozen=True, slots=True)
class PlatformRepositoryVersion:
    id: UUID
    study_id: UUID
    object_id: UUID
    filename: str
    media_type: str
    sha256: str
    size: int
    classification: str
    source_status: str


class PlatformObjectClient:
    """Authorize downloads without revealing storage keys or credentials."""

    def __init__(
        self,
        settings: Settings,
        authorization: PlatformAuthorizationClient,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.mode = settings.platform_authorization_mode
        self._base_url = (settings.platform_control_plane_url or "").rstrip("/")
        self._authorization = authorization
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=settings.platform_authorization_timeout_seconds,
        )

    async def authorize_download(self, object_id: UUID) -> str:
        """Return a short-lived URL after gateway authorization."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform object gateway is not configured")
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/objects/{object_id}/download",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json={"authorization_action": "edc.file.upload"},
            )
            response.raise_for_status()
            url = str(response.json()["url"])
            if not url:
                raise ValueError("empty object URL")
            return url
        except ServiceUnavailableError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform object gateway is temporarily unavailable"
            ) from error

    async def register_bytes(
        self,
        *,
        study_id: UUID,
        content: bytes,
        media_type: str,
        classification: str,
        external_reference: str,
        retention_until: datetime | None = None,
        repository: dict[str, object] | None = None,
    ) -> PlatformObjectRegistration:
        """Upload verified bytes and register the EDC-owned reference."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform object gateway is not configured")
        headers = {"Authorization": f"Bearer {self._authorization.service_token()}"}
        digest = hashlib.sha256(content).hexdigest()
        command = {
            "study_id": str(study_id),
            "owner_product": "aurinara-edc",
            "authorization_action": "edc.file.upload",
            "classification": classification,
            "media_type": media_type,
            "expected_sha256": digest,
            "expected_size_bytes": len(content),
            "part_count": 1,
            "retention_until": retention_until.isoformat() if retention_until else None,
        }
        try:
            created = await self._client.post(
                f"{self._base_url}/v1/objects/upload-sessions",
                headers=headers,
                json=command,
            )
            if created.status_code == 409:
                object_id = UUID(created.json()["error"]["details"]["object_id"])
            else:
                created.raise_for_status()
                payload = created.json()
                object_id = UUID(payload["object_id"])
                upload_url = str(payload["parts"][0]["url"])
                uploaded = await self._client.put(
                    upload_url,
                    content=content,
                    headers={"Content-Type": media_type},
                )
                uploaded.raise_for_status()
                etag = uploaded.headers.get("ETag")
                if not etag:
                    raise ValueError("upload response did not include an ETag")
                finalized = await self._client.post(
                    f"{self._base_url}/v1/objects/{object_id}/finalize",
                    headers=headers,
                    json={"parts": [{"part_number": 1, "etag": etag}]},
                )
                finalized.raise_for_status()
            referenced = await self._client.post(
                f"{self._base_url}/v1/objects/{object_id}/references",
                headers=headers,
                json={
                    "product": "aurinara-edc",
                    "authorization_action": "edc.file.upload",
                    "external_reference": external_reference,
                    "idempotency_key": external_reference,
                    **({"repository": repository} if repository is not None else {}),
                },
            )
            referenced.raise_for_status()
            return PlatformObjectRegistration(
                object_id=object_id,
                reference_id=UUID(referenced.json()["id"]),
            )
        except ServiceUnavailableError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform object gateway is temporarily unavailable"
            ) from error

    async def resolve_repository_version(
        self, version_id: UUID, user_access_token: str
    ) -> PlatformRepositoryVersion:
        """Resolve Repository metadata with the signed-in user's token."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform object gateway is not configured")
        try:
            response = await self._client.get(
                f"{self._base_url}/v1/repository/versions/{version_id}",
                headers={"Authorization": f"Bearer {user_access_token}"},
            )
            response.raise_for_status()
            payload = response.json()
            return PlatformRepositoryVersion(
                id=UUID(payload["id"]),
                study_id=UUID(payload["study_id"]),
                object_id=UUID(payload["object_id"]),
                filename=str(payload["filename"]),
                media_type=str(payload["media_type"]),
                sha256=str(payload["sha256"]),
                size=int(payload["size_bytes"]),
                classification=str(payload["classification"]),
                source_status=str(payload["source_status"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform object gateway is temporarily unavailable"
            ) from error

    async def bind_repository_object(
        self, *, object_id: UUID, external_reference: str
    ) -> PlatformObjectRegistration:
        """Create the EDC reference for an explicitly selected Repository version."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform object gateway is not configured")
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/objects/{object_id}/references",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
                json={
                    "product": "aurinara-edc",
                    "authorization_action": "edc.file.upload",
                    "external_reference": external_reference,
                    "idempotency_key": external_reference,
                },
            )
            response.raise_for_status()
            return PlatformObjectRegistration(
                object_id=object_id,
                reference_id=UUID(response.json()["id"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ServiceUnavailableError(
                "Platform object gateway is temporarily unavailable"
            ) from error

    async def release_reference(self, reference_id: UUID) -> None:
        """Idempotently release one product reference after local retention permits it."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform object gateway is not configured")
        try:
            response = await self._client.delete(
                f"{self._base_url}/v1/object-references/{reference_id}",
                headers={"Authorization": f"Bearer {self._authorization.service_token()}"},
            )
            response.raise_for_status()
        except ServiceUnavailableError:
            raise
        except httpx.HTTPError as error:
            raise ServiceUnavailableError(
                "Platform object gateway is temporarily unavailable"
            ) from error


_objects: PlatformObjectClient | None = None


def get_platform_objects() -> PlatformObjectClient:
    global _objects
    if _objects is None:
        settings = get_settings()
        _objects = PlatformObjectClient(settings, get_platform_authorization())
    return _objects


def reset_platform_objects() -> None:
    """Reset the singleton after settings overrides in tests."""

    global _objects
    _objects = None
