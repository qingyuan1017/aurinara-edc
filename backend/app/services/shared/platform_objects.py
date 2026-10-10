"""Client for opaque objects served by the shared platform gateway."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError
from app.services.shared.platform_authorization import (
    PlatformAuthorizationClient,
    get_platform_authorization,
)


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
    ) -> UUID:
        """Upload verified bytes and register the EDC-owned reference."""

        if not self._base_url:
            raise ServiceUnavailableError("Platform object gateway is not configured")
        headers = {"Authorization": f"Bearer {self._authorization.service_token()}"}
        digest = hashlib.sha256(content).hexdigest()
        command = {
            "study_id": str(study_id),
            "owner_product": "aurinara-edc",
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
                    "external_reference": external_reference,
                },
            )
            referenced.raise_for_status()
            return object_id
        except ServiceUnavailableError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
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
