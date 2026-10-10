from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.services.shared.platform_authorization import PlatformAuthorizationClient
from app.services.shared.platform_objects import PlatformObjectClient


@pytest.mark.asyncio
async def test_object_download_returns_gateway_url_without_storage_key() -> None:
    object_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/objects/{object_id}/download"
        assert request.headers["Authorization"] == "Bearer service-token"
        return httpx.Response(
            200,
            json={
                "url": "https://objects.test/signed",
                "expires_at": "2026-10-10T00:00:00Z",
            },
        )

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_identity_issuer="https://issuer.test",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    authorization = PlatformAuthorizationClient(settings)
    authorization._token = ("service-token", float("inf"))
    client = PlatformObjectClient(settings, authorization, httpx.MockTransport(handler))

    assert await client.authorize_download(object_id) == "https://objects.test/signed"
    await client._client.aclose()


@pytest.mark.asyncio
async def test_register_bytes_uses_presigned_upload_and_opaque_reference() -> None:
    object_id = uuid4()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/v1/objects/upload-sessions":
            return httpx.Response(
                201,
                json={
                    "object_id": str(object_id),
                    "upload_id": "upload-1",
                    "expires_at": "2026-10-10T00:00:00Z",
                    "parts": [{"part_number": 1, "url": "https://upload.test/part"}],
                },
            )
        if request.url.host == "upload.test":
            return httpx.Response(200, headers={"ETag": '"etag"'})
        if request.url.path.endswith("/finalize"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/references"):
            return httpx.Response(201, json={})
        raise AssertionError(request.url)

    settings = Settings(
        _env_file=None,
        app_env="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_identity_issuer="https://issuer.test",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    authorization = PlatformAuthorizationClient(settings)
    authorization._token = ("service-token", float("inf"))
    client = PlatformObjectClient(settings, authorization, httpx.MockTransport(handler))

    result = await client.register_bytes(
        study_id=uuid4(),
        content=b"verified",
        media_type="application/pdf",
        classification="clinical-attachment",
        external_reference="file_attachment:1",
    )

    assert result == object_id
    assert seen == [
        "/v1/objects/upload-sessions",
        "/part",
        f"/v1/objects/{object_id}/finalize",
        f"/v1/objects/{object_id}/references",
    ]
    await client._client.aclose()
