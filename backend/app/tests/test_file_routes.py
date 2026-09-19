"""Focused route tests for file attachment upload, download, and deletion."""

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from app.api.routes.files import delete_file, download_file, upload_file
from app.core.exceptions import NotFoundError
from app.main import create_app
from app.models.file_attachment import FileAttachment
from app.schemas.file_attachment import FileAttachmentDelete, FileAttachmentResponse


def _attachment() -> FileAttachment:
    return FileAttachment(
        id=uuid4(),
        object_type="study",
        object_id=uuid4(),
        study_id=uuid4(),
        filename="source document.pdf",
        content_type="application/pdf",
        size_bytes=7,
        storage_key="files/source-document.pdf",
        uploaded_by=uuid4(),
        uploaded_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_upload_route_delegates_multipart_file_and_returns_metadata(monkeypatch):
    attachment = _attachment()
    service = SimpleNamespace(upload=AsyncMock(return_value=attachment))
    monkeypatch.setattr("app.api.routes.files.file_attachment_service", service)

    user = SimpleNamespace(id=uuid4())
    session = AsyncMock()
    upload = UploadFile(BytesIO(b"pdf data"), filename="source document.pdf")

    response = await upload_file("study", attachment.object_id, upload, session, user)

    assert isinstance(response, FileAttachmentResponse)
    assert response.id == attachment.id
    service.upload.assert_awaited_once_with(
        session=session,
        parent=attachment.object_id,
        file=upload,
        actor_id=user.id,
        user=user,
        object_type="study",
        object_id=attachment.object_id,
    )


@pytest.mark.asyncio
async def test_download_route_returns_bytes_and_content_metadata(monkeypatch):
    attachment = _attachment()
    session = AsyncMock()
    session.get.return_value = attachment
    service = SimpleNamespace(download=AsyncMock(return_value=b"pdf data"))
    monkeypatch.setattr("app.api.routes.files.file_attachment_service", service)
    user = SimpleNamespace(id=uuid4())

    response = await download_file(attachment.id, session, user)

    assert response.status_code == 200
    assert response.body == b"pdf data"
    assert response.media_type == "application/pdf"
    assert 'filename="source document.pdf"' in response.headers["content-disposition"]
    service.download.assert_awaited_once_with(session, attachment, user)


@pytest.mark.asyncio
async def test_delete_route_passes_reason_to_soft_delete(monkeypatch):
    attachment = _attachment()
    service = SimpleNamespace(soft_delete=AsyncMock(return_value=attachment))
    monkeypatch.setattr("app.api.routes.files.file_attachment_service", service)
    user = SimpleNamespace(id=uuid4())
    session = AsyncMock()
    body = FileAttachmentDelete(reason="Entered in error")

    response = await delete_file(attachment.id, body, session, user)

    assert response.id == attachment.id
    service.soft_delete.assert_awaited_once_with(
        session=session,
        attachment=attachment.id,
        reason="Entered in error",
        actor_id=user.id,
        user=user,
    )


@pytest.mark.asyncio
async def test_download_route_uses_standard_not_found_error():
    session = AsyncMock()
    session.get.return_value = None

    with pytest.raises(NotFoundError, match="File attachment not found"):
        await download_file(uuid4(), session, SimpleNamespace(id=uuid4()))


def test_file_routes_are_registered_under_api_v1():
    paths = create_app().openapi()["paths"]

    assert "/api/v1/objects/{object_type}/{object_id}/files" in paths
    assert "/api/v1/files/{file_id}/download" in paths
    assert "/api/v1/files/{file_id}" in paths
    assert "post" in paths["/api/v1/objects/{object_type}/{object_id}/files"]
    assert "get" in paths["/api/v1/files/{file_id}/download"]
    assert "delete" in paths["/api/v1/files/{file_id}"]
