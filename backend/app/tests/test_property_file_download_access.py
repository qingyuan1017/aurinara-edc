"""Property-based test for scoped file attachment downloads.

# Feature: clinical-edc-system, Property 35: File download requires parent read access

**Validates: Requirements 27.1, 27.2**

For any supported file parent and user scope, a download succeeds only when
that user has the parent-specific read permission at the attachment's study/site
scope. Missing permissions and grants outside the attachment's object scope are
denied before storage access or download auditing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import AuthorizationError
from app.models.file_attachment import FileAttachment, FileAttachmentObjectType
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.services.file_attachment_service import FileAttachmentService
from app.services.permission_service import PermissionService

PARENT_READ_PERMISSIONS = {
    FileAttachmentObjectType.field: "form.read",
    FileAttachmentObjectType.form: "form.read",
    FileAttachmentObjectType.visit: "subject.read",
    FileAttachmentObjectType.subject: "subject.read",
    FileAttachmentObjectType.site: "site.read",
    FileAttachmentObjectType.study: "study.read",
}


class MemoryStorage:
    """Small object-storage implementation that records reads for assertions."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.get_calls: list[str] = []

    async def get(self, key: str) -> bytes:
        self.get_calls.append(key)
        return self.objects[key]


@st.composite
def download_case_strategy(draw):
    """Generate parent types, scopes, and authorization outcomes."""
    object_type = draw(st.sampled_from(list(FileAttachmentObjectType)))
    study_id = draw(st.uuids())
    site_id = None if object_type is FileAttachmentObjectType.study else draw(st.uuids())
    mode = draw(st.sampled_from(["authorized", "missing_read", "out_of_scope"]))
    required_permission = PARENT_READ_PERMISSIONS[object_type]

    if mode == "authorized":
        grant = {
            "permission_code": required_permission,
            "study_id": study_id,
            "site_id": site_id,
        }
    elif mode == "missing_read":
        grant = {
            "permission_code": (
                "subject.read" if required_permission != "subject.read" else "form.read"
            ),
            "study_id": study_id,
            "site_id": site_id,
        }
    elif object_type is FileAttachmentObjectType.study:
        grant = {
            "permission_code": required_permission,
            "study_id": uuid.uuid4(),
            "site_id": None,
        }
    else:
        grant = {
            "permission_code": required_permission,
            "study_id": study_id,
            "site_id": uuid.uuid4(),
        }

    return {
        "object_type": object_type,
        "study_id": study_id,
        "site_id": site_id,
        "mode": mode,
        "grant": grant,
    }


def _user_with_grant(grant: dict) -> MagicMock:
    """Build the minimal identity graph consumed by PermissionService."""
    permission = MagicMock(spec=Permission)
    permission.code = grant["permission_code"]

    role_permission = MagicMock(spec=RolePermission)
    role_permission.permission = permission

    role = MagicMock(spec=Role)
    role.role_permissions = [role_permission]

    user_role = MagicMock(spec=UserRole)
    user_role.role = role
    user_role.study_id = grant["study_id"]
    user_role.site_id = grant["site_id"]

    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.user_roles = [user_role]
    return user


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


class TestFileDownloadAccessProperty:
    """Property 35: file downloads require parent read access and object scope."""

    @settings(max_examples=150, deadline=None)
    @given(case=download_case_strategy())
    async def test_download_is_granted_only_for_scoped_parent_read_access(self, case):
        """Authorized users receive bytes and a download audit; others do not.

        **Validates: Requirements 27.1, 27.2**
        """
        user = _user_with_grant(case["grant"])
        storage = MemoryStorage()
        attachment_id = uuid.uuid4()
        storage_key = f"files/{attachment_id}/source.pdf"
        content = b"source document"
        storage.objects[storage_key] = content
        attachment = FileAttachment(
            id=attachment_id,
            object_type=case["object_type"].value,
            object_id=uuid.uuid4(),
            study_id=case["study_id"],
            site_id=case["site_id"],
            filename="source.pdf",
            content_type="application/pdf",
            size_bytes=len(content),
            storage_key=storage_key,
            uploaded_by=uuid.uuid4(),
        )
        service = FileAttachmentService(
            storage=storage,
            permission_service=PermissionService(),
        )

        with patch("app.services.file_attachment_service.audit_service") as audit:
            audit.record = AsyncMock()
            if case["mode"] == "authorized":
                assert await service.download(_session(), attachment, user) == content
                assert storage.get_calls == [storage_key]
                audit.record.assert_awaited_once()
                assert audit.record.call_args.kwargs["action"] == "download"
                assert audit.record.call_args.kwargs["entity_id"] == attachment_id
                assert audit.record.call_args.kwargs["actor_id"] == user.id
            else:
                with pytest.raises(AuthorizationError):
                    await service.download(_session(), attachment, user)
                assert storage.get_calls == []
                audit.record.assert_not_awaited()
