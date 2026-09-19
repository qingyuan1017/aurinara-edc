"""Focused tests for File_Attachment_Service.

Validates Requirements 27.1-27.5 and 18.4: storage/metadata linkage,
lock rejection, parent-read enforcement, soft-delete retention, and audits.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, ValidationError
from app.core.storage import LocalObjectStorage
from app.models.file_attachment import FileAttachment
from app.models.study import Study
from app.services.file_attachment_service import FileAttachmentService
from app.services.permission_service import PermissionService


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, bytes, str]] = []

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.put_calls.append((key, content, content_type))
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def actor_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def study(actor_id: uuid.UUID) -> Study:
    return Study(
        id=uuid.uuid4(),
        study_code="ATT-001",
        title="Attachment Study",
        created_by=actor_id,
        created_at=datetime.now(UTC),
    )


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_local_storage_round_trip(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    await storage.put("study/file.txt", b"source", "text/plain")
    assert await storage.get("study/file.txt") == b"source"


@pytest.mark.asyncio
async def test_upload_stores_metadata_and_audits(study, actor_id):
    storage = MemoryStorage()
    locks = MagicMock()
    locks.is_modification_blocked = AsyncMock(return_value=False)
    service = FileAttachmentService(storage=storage, lock_service_instance=locks)
    session = _session()

    with patch("app.services.file_attachment_service.audit_service") as audit:
        audit.record = AsyncMock()
        attachment = await service.upload(
            session,
            study,
            b"supporting document",
            actor_id,
        )

    assert attachment.object_type == "study"
    assert attachment.object_id == study.id
    assert attachment.study_id == study.id
    assert attachment.filename == "attachment"
    assert attachment.size_bytes == len(b"supporting document")
    assert storage.objects[attachment.storage_key] == b"supporting document"
    locks.is_modification_blocked.assert_awaited_once()
    audit.record.assert_awaited_once()
    assert audit.record.call_args.kwargs["action"] == "upload"
    assert audit.record.call_args.kwargs["entity_id"] == attachment.id


@pytest.mark.asyncio
async def test_upload_rejects_frozen_or_locked_parent_before_storage(study, actor_id):
    storage = MemoryStorage()
    locks = MagicMock()
    locks.is_modification_blocked = AsyncMock(return_value=True)
    service = FileAttachmentService(storage=storage, lock_service_instance=locks)

    with pytest.raises(ConflictError, match="frozen or locked"):
        await service.upload(_session(), study, b"blocked", actor_id)

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_download_requires_parent_read_access_and_audits(actor_id):
    study_id = uuid.uuid4()
    attachment = FileAttachment(
        id=uuid.uuid4(),
        object_type="study",
        object_id=study_id,
        study_id=study_id,
        filename="source.pdf",
        content_type="application/pdf",
        size_bytes=6,
        storage_key="files/source.pdf",
        uploaded_by=uuid.uuid4(),
    )
    storage = MemoryStorage()
    storage.objects[attachment.storage_key] = b"source"
    permissions = MagicMock(spec=PermissionService)
    service = FileAttachmentService(storage=storage, permission_service=permissions)
    user = MagicMock(id=actor_id)

    with patch("app.services.file_attachment_service.audit_service") as audit:
        audit.record = AsyncMock()
        content = await service.download(_session(), attachment, user)

    assert content == b"source"
    permissions.require.assert_called_once_with(
        user,
        "study.read",
        study_id=study_id,
        site_id=None,
    )
    permissions.assert_object_access.assert_called_once_with(user, attachment)
    assert audit.record.call_args.kwargs["action"] == "download"
    assert audit.record.call_args.kwargs["actor_id"] == actor_id


@pytest.mark.asyncio
async def test_soft_delete_retains_metadata_and_audits(actor_id):
    attachment = FileAttachment(
        id=uuid.uuid4(),
        object_type="study",
        object_id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        filename="source.pdf",
        content_type="application/pdf",
        size_bytes=6,
        storage_key="files/source.pdf",
        uploaded_by=uuid.uuid4(),
    )
    storage = MemoryStorage()
    storage.objects[attachment.storage_key] = b"source"
    service = FileAttachmentService(storage=storage)

    with patch("app.services.file_attachment_service.audit_service") as audit:
        audit.record = AsyncMock()
        result = await service.soft_delete(_session(), attachment, "Entered in error", actor_id)

    assert result.id == attachment.id
    assert result.storage_key == "files/source.pdf"
    assert result.deleted_at is not None
    assert result.deleted_at.tzinfo is not None
    assert result.deleted_by == actor_id
    assert result.delete_reason == "Entered in error"
    assert storage.objects[attachment.storage_key] == b"source"
    assert audit.record.call_args.kwargs["action"] == "delete"
    assert audit.record.call_args.kwargs["reason"] == "Entered in error"


@pytest.mark.asyncio
async def test_soft_delete_requires_reason(actor_id):
    attachment = FileAttachment(
        id=uuid.uuid4(),
        object_type="study",
        object_id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        filename="source.pdf",
        content_type="application/pdf",
        size_bytes=0,
        storage_key="files/source.pdf",
        uploaded_by=uuid.uuid4(),
    )
    service = FileAttachmentService(storage=MemoryStorage())

    with pytest.raises(ValidationError, match="deletion reason"):
        await service.soft_delete(_session(), attachment, "  ", actor_id)


@pytest.mark.asyncio
async def test_upload_operational_uses_ctms_metadata_safe_key_and_audit(actor_id):
    storage = MemoryStorage()
    permissions = MagicMock(spec=PermissionService)
    service = FileAttachmentService(storage=storage, permission_service=permissions)
    session = _session()
    study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    upload = SimpleNamespace(
        filename="../../monitoring notes.pdf",
        content_type="application/pdf; charset=binary",
        read=lambda: b"operational evidence",
    )
    user = MagicMock(id=actor_id)

    with patch("app.services.file_attachment_service.audit_service") as audit:
        audit.record = AsyncMock()
        attachment = await service.upload_operational(
            session,
            parent_type="monitoring_activity",
            parent_id=uuid.uuid4(),
            study_id=study_id,
            site_id=site_id,
            file=upload,
            actor_id=actor_id,
            user=user,
            retention_until=datetime(2030, 1, 1, tzinfo=UTC),
            correlation_id="corr-operational-upload",
        )

    assert attachment.module == "CTMS"
    assert attachment.attachment_type == "Operational_Attachment"
    assert attachment.object_type == "operational"
    assert attachment.correlation_id == "corr-operational-upload"
    assert attachment.filename == ".._.._monitoring notes.pdf"
    assert attachment.storage_key.startswith(f"ctms-files/{study_id}/{attachment.id}")
    assert ".." not in attachment.storage_key
    permissions.require.assert_called_once_with(
        user,
        "ctms.monitoring-activity-management",
        study_id=study_id,
        site_id=site_id,
    )
    assert storage.objects[attachment.storage_key] == b"operational evidence"
    assert audit.record.await_args.kwargs["module"].value == "CTMS"
    assert audit.record.await_args.kwargs["correlation_id"] == "corr-operational-upload"


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_type", ["form", "field", "query", "clinical_attachment"])
async def test_upload_operational_rejects_clinical_parent_types(parent_type, actor_id):
    storage = MemoryStorage()
    service = FileAttachmentService(storage=storage)

    with pytest.raises(ValidationError, match="CTMS-owned parent"):
        await service.upload_operational(
            _session(),
            parent_type=parent_type,
            parent_id=uuid.uuid4(),
            study_id=uuid.uuid4(),
            file=SimpleNamespace(
                filename="notes.pdf", content_type="application/pdf", read=lambda: b"data"
            ),
            actor_id=actor_id,
        )

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_upload_operational_rejects_unapproved_mime_type_before_storage(actor_id):
    storage = MemoryStorage()
    service = FileAttachmentService(storage=storage)

    with pytest.raises(ValidationError, match="MIME type"):
        await service.upload_operational(
            _session(),
            parent_type="task",
            parent_id=uuid.uuid4(),
            study_id=uuid.uuid4(),
            file=SimpleNamespace(
                filename="payload.exe", content_type="application/x-msdownload", read=lambda: b"data"
            ),
            actor_id=actor_id,
        )

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_operational_delete_restore_and_purge_are_audited_and_retention_guarded(actor_id):
    storage = MemoryStorage()
    permissions = MagicMock(spec=PermissionService)
    service = FileAttachmentService(storage=storage, permission_service=permissions)
    attachment = FileAttachment(
        id=uuid.uuid4(),
        module="CTMS",
        attachment_type="Operational_Attachment",
        object_type="operational",
        object_id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        filename="evidence.pdf",
        content_type="application/pdf",
        size_bytes=7,
        storage_key="ctms-files/evidence.pdf",
        uploaded_by=actor_id,
        retention_until=datetime(2020, 1, 1, tzinfo=UTC),
    )
    storage.objects[attachment.storage_key] = b"evidence"
    user = MagicMock(id=actor_id)

    with patch("app.services.file_attachment_service.audit_service") as audit:
        audit.record = AsyncMock()
        await service.soft_delete(
            _session(), attachment, "retention complete", actor_id, user=user,
            correlation_id="corr-delete",
        )
        assert attachment.deleted_at is not None
        await service.restore(
            _session(), attachment, actor_id, reason="retention restore", user=user,
            correlation_id="corr-restore"
        )
        await service.archive(
            _session(), attachment, "retention archived", actor_id, user=user,
            correlation_id="corr-archive", now=datetime(2021, 1, 1, tzinfo=UTC),
        )
        await service.purge(
            _session(), attachment, actor_id, user=user,
            correlation_id="corr-purge", now=datetime(2021, 1, 2, tzinfo=UTC),
        )

    assert attachment.archived_at is not None
    assert attachment.archive_reason == "retention archived"
    assert attachment.storage_key not in storage.objects
    assert [call.kwargs["action"] for call in audit.record.await_args_list] == [
        "delete", "restore", "archive", "purge"
    ]
    assert all(call.kwargs["module"] == "CTMS" for call in audit.record.await_args_list)
