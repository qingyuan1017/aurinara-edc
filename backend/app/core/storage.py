"""Object-storage abstraction used by file attachments.

The service layer only depends on ``ObjectStorage`` so local development and
S3-compatible deployments use the same upload/download contract.  Local
storage is deliberately the default because it is the repository's existing
Phase 1 convention; S3 support is lazy and requires the optional boto3 client
only when an S3 backend is configured.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationError


class ObjectStorage(Protocol):
    """Minimal async object-storage contract for attachment bytes."""

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store bytes under ``key``."""

    async def get(self, key: str) -> bytes:
        """Read bytes stored under ``key``."""

    async def delete(self, key: str) -> None:
        """Delete an object after its retention policy permits physical removal."""


class LocalObjectStorage:
    """Store objects beneath a configured local directory."""

    def __init__(self, root: str | Path = "attachments") -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValidationError(
                message="Invalid object storage key",
                details={"key": key},
            )
        return candidate

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Write an object atomically enough for local development storage."""
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    async def get(self, key: str) -> bytes:
        """Read an object, preserving ``FileNotFoundError`` for the service."""
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        """Remove an object; missing objects are already in the desired state."""
        path = self._path(key)

        def _unlink() -> None:
            try:
                path.unlink()
            except FileNotFoundError:
                return

        await asyncio.to_thread(_unlink)


class S3CompatibleObjectStorage:
    """S3-compatible storage adapter with a lazily-created boto3 client.

    ``boto3`` is intentionally imported only when this backend is used.  This
    keeps local/test installations lightweight while supporting AWS S3 and
    compatible endpoints such as MinIO when the deployment supplies boto3.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: object | None = None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self._client = client

    def _get_client(self) -> object:
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - deployment-only path
                raise ValidationError(
                    message="S3-compatible storage requires the boto3 package",
                    details={},
                ) from exc
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
            )
        return self._client

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        client = self._get_client()
        await asyncio.to_thread(
            client.put_object,  # type: ignore[attr-defined]
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        client = self._get_client()
        response = await asyncio.to_thread(
            client.get_object,  # type: ignore[attr-defined]
            Bucket=self.bucket,
            Key=key,
        )
        body = response["Body"]
        return await asyncio.to_thread(body.read)

    async def delete(self, key: str) -> None:
        """Delete an object only when the owning retention policy allows it."""
        client = self._get_client()
        await asyncio.to_thread(
            client.delete_object,  # type: ignore[attr-defined]
            Bucket=self.bucket,
            Key=key,
        )


def get_object_storage(settings: Settings | None = None) -> ObjectStorage:
    """Build the configured attachment storage backend."""
    settings = settings or get_settings()
    backend = settings.object_storage_backend.lower()
    if backend in {"s3", "s3-compatible", "s3_compatible"} or settings.s3_bucket_name:
        if not settings.s3_bucket_name:
            raise ValidationError(
                message="S3-compatible storage requires a bucket name",
                details={},
            )
        return S3CompatibleObjectStorage(
            bucket=settings.s3_bucket_name,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
        )
    if backend != "local":
        raise ValidationError(
            message="Unsupported object storage backend",
            details={"backend": settings.object_storage_backend},
        )
    return LocalObjectStorage(settings.object_storage_local_dir)
