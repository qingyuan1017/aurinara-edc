"""Property 18: export and attachment ownership is separated.

**Validates: Requirements 2.7–2.8, 8.4, 10.11, 11.5, 12.6–12.12, 12.15**

The property exercises the shared export and file-storage primitives with
module-owned content. CTMS jobs and operational attachments share lifecycle and
audit infrastructure, but clinical exports/attachments remain EDC-owned and
cannot be read through CTMS permissions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ctms import Module
from app.core.exceptions import AuthorizationError, ValidationError
from app.models.file_attachment import (
    FileAttachment,
    FileAttachmentModule,
    FileAttachmentObjectType,
)
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.export import ExportStatus
from app.services.export_service import ExportService
from app.services.file_attachment_service import FileAttachmentService
from app.workers.ctms_export_worker import _row_for, run_ctms_export


class _MemoryStorage:
    """Deterministic object store used by the generated attachment cases."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.get_calls: list[str] = []

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        self.get_calls.append(key)
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _Upload:
    def __init__(self, content: bytes, filename: str, content_type: str) -> None:
        self.content = content
        self.filename = filename
        self.content_type = content_type

    def read(self) -> bytes:
        return self.content


class _Session:
    """Minimal async session for service paths that receive model instances."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush = AsyncMock()

    def add(self, value: object) -> None:
        self.added.append(value)


@st.composite
def ownership_case(draw: st.DrawFn) -> dict[str, object]:
    """Generate owners, scope outcomes, filters, and operational content."""

    study_id = draw(st.uuids(version=4))
    site_id = draw(st.uuids(version=4))
    other_study_id = draw(st.uuids(version=4).filter(lambda value: value != study_id))
    other_site_id = draw(st.uuids(version=4).filter(lambda value: value != site_id))
    scope_mode = draw(st.sampled_from(("authorized", "missing_permission", "out_of_scope")))
    export_owner = draw(st.sampled_from((Module.CTMS.value, Module.EDC.value)))
    content = draw(
        st.binary(min_size=0, max_size=64).map(lambda value: value or b"operational-bytes")
    )
    label = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
            min_size=1,
            max_size=16,
        )
    )
    return {
        "study_id": study_id,
        "site_id": site_id,
        "other_study_id": other_study_id,
        "other_site_id": other_site_id,
        "scope_mode": scope_mode,
        "export_owner": export_owner,
        "content": content,
        "label": label,
        "correlation_id": f"corr-{label}",
        "filters": {"record_types": ["operational_task"], "page": 1, "page_size": 1},
    }


def _ctms_user(case: dict[str, object]) -> MagicMock:
    """Build a user with generated CTMS permissions and generated scope."""

    permissions = [
        "ctms.operational-study-management",
        "ctms.operational-data-read",
    ]
    role_permissions = []
    for code in permissions:
        permission = MagicMock(spec=Permission)
        permission.code = code
        role_permission = MagicMock(spec=RolePermission)
        role_permission.permission = permission
        role_permissions.append(role_permission)

    role = MagicMock(spec=Role)
    role.role_permissions = role_permissions
    assignment = MagicMock(spec=UserRole)
    assignment.role = role
    if case["scope_mode"] == "authorized":
        assignment.study_id = case["study_id"]
        assignment.site_id = case["site_id"]
    elif case["scope_mode"] == "out_of_scope":
        assignment.study_id = case["other_study_id"]
        assignment.site_id = case["other_site_id"]
    else:
        assignment.study_id = case["study_id"]
        assignment.site_id = case["site_id"]
        # The permissions are deliberately replaced with an unrelated grant.
        unrelated = MagicMock(spec=Permission)
        unrelated.code = "ctms.dashboard-read"
        unrelated_role_permission = MagicMock(spec=RolePermission)
        unrelated_role_permission.permission = unrelated
        role.role_permissions = [unrelated_role_permission]

    user = MagicMock(spec=User)
    user.id = uuid4()
    user.user_roles = [assignment]
    return user


def _clinical_attachment(case: dict[str, object], content: bytes) -> FileAttachment:
    attachment_id = uuid4()
    return FileAttachment(
        id=attachment_id,
        module=FileAttachmentModule.EDC.value,
        attachment_type="Clinical_Attachment",
        object_type=FileAttachmentObjectType.study.value,
        object_id=case["study_id"],
        study_id=case["study_id"],
        filename="clinical-source.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        storage_key=f"edc-files/{attachment_id}",
        uploaded_by=uuid4(),
    )


@settings(max_examples=100, deadline=None)
@given(case=ownership_case())
@pytest.mark.asyncio
async def test_export_and_attachment_ownership_is_separated(case: dict[str, object]) -> None:
    """Shared lifecycle controls never transfer content ownership."""

    study_id = case["study_id"]
    site_id = case["site_id"]
    actor_id = uuid4()
    session = _Session()
    audit_calls: list[dict[str, object]] = []

    async def record_audit(_session, **kwargs):
        audit_calls.append(kwargs)
        return MagicMock()

    export_service = ExportService()
    with patch("app.services.export_service.audit_service.record", side_effect=record_audit):
        ctms_export = await export_service.create_ctms_export(
            session,
            study_id=study_id,
            export_type="json",
            filters=case["filters"],
            actor_id=actor_id,
            correlation_id=case["correlation_id"],
        )
        assert ctms_export.module == Module.CTMS.value
        assert ctms_export.content_owner == Module.CTMS.value
        assert ctms_export.status == ExportStatus.queued

        await export_service.start_export(session, ctms_export)
        await export_service.complete_export(
            session,
            ctms_export,
            file_path=f"exports/ctms/{ctms_export.id}.json",
            file_size=len(case["content"]),
        )
        await export_service.record_download(
            session,
            ctms_export,
            actor_id=actor_id,
            correlation_id=case["correlation_id"],
        )

    assert ctms_export.status == ExportStatus.completed
    export_actions = [
        call["action"]
        for call in audit_calls
        if call["entity_type"] == "export"
    ]
    assert export_actions == ["create", "download"]
    assert all(call["module"] == Module.CTMS for call in audit_calls)
    assert all(call["scope"] == {"study_id": study_id} for call in audit_calls)
    assert audit_calls[-1]["correlation_id"] == case["correlation_id"]

    # An EDC-owned clinical export remains valid shared metadata but cannot be
    # created as a CTMS job or dispatched to the CTMS content worker.
    edc_session = _Session()
    with patch("app.services.export_service.audit_service.record", new_callable=AsyncMock):
        edc_export = await export_service.create_export(
            edc_session,
            study_id=study_id,
            export_type="csv",
            filters={"clinical_data": True},
            actor_id=actor_id,
            module=Module.EDC,
            content_owner=Module.EDC,
        )
    assert edc_export.module == Module.EDC.value
    assert edc_export.content_owner == Module.EDC.value
    with pytest.raises(ValueError, match="CTMS-owned"):
        await run_ctms_export(AsyncMock(), edc_export)
    with pytest.raises(ValidationError, match="content owner"):
        await export_service.create_export(
            _Session(),
            study_id=study_id,
            export_type="csv",
            actor_id=actor_id,
            module=Module.CTMS,
            content_owner=Module.EDC,
        )

    # The export row is built from the operational allowlist only, even when a
    # generated operational record carries clinical-looking fields.
    operational_token = f"operational-{case['label']}"
    clinical_token = f"clinical-secret-{case['label']}"
    operational_record = SimpleNamespace(
        id=uuid4(),
        study_id=study_id,
        site_id=site_id,
        status="Open",
        title=operational_token,
        owner_id=actor_id,
        due_date=datetime.now(UTC),
        priority="High",
        description=clinical_token,
        clinical_data=clinical_token,
        query_summary=clinical_token,
        source_document=clinical_token,
    )
    row = _row_for("operational_task", operational_record)
    assert row["title"] == operational_token
    assert clinical_token not in repr(row)

    user = _ctms_user(case)
    storage = _MemoryStorage()
    attachment_service = FileAttachmentService(storage=storage)
    attachment_session = _Session()
    upload = _Upload(case["content"], f"ops-{case['label']}.txt", "text/plain")

    with patch("app.services.file_attachment_service.audit_service.record", side_effect=record_audit):
        if case["scope_mode"] == "authorized":
            attachment = await attachment_service.upload_operational(
                attachment_session,
                parent_type="operational_task",
                parent_id=uuid4(),
                study_id=study_id,
                site_id=site_id,
                file=upload,
                actor_id=actor_id,
                user=user,
                correlation_id=case["correlation_id"],
            )
            assert attachment.module == Module.CTMS.value
            assert attachment.attachment_type == "Operational_Attachment"
            assert attachment.object_type == FileAttachmentObjectType.operational.value
            assert storage.objects[attachment.storage_key] == case["content"]

            assert await attachment_service.download(attachment_session, attachment, user) == case["content"]
            await attachment_service.soft_delete(
                attachment_session,
                attachment,
                "generated retention action",
                actor_id,
                user=user,
                correlation_id=case["correlation_id"],
            )
            await attachment_service.restore(
                attachment_session,
                attachment,
                actor_id,
                reason="generated restore action",
                user=user,
                correlation_id=case["correlation_id"],
            )
            attachment_actions = [
                call["action"]
                for call in audit_calls
                if call["entity_type"] == "operational_attachment"
                and call["entity_id"] == attachment.id
            ]
            assert attachment_actions == ["upload", "download", "delete", "restore"]
            assert all(
                call["module"] == Module.CTMS
                and call["scope"] == {"study_id": study_id, "site_id": site_id}
                for call in audit_calls
                if call["entity_type"] == "operational_attachment"
                and call["entity_id"] == attachment.id
            )
        else:
            with pytest.raises(AuthorizationError):
                await attachment_service.upload_operational(
                    attachment_session,
                    parent_type="operational_task",
                    parent_id=uuid4(),
                    study_id=study_id,
                    site_id=site_id,
                    file=upload,
                    actor_id=actor_id,
                    user=user,
                    correlation_id=case["correlation_id"],
                )
            assert storage.objects == {}

    # CTMS operational permissions never authorize a clinical attachment read,
    # even when the caller has the correct CTMS study/site scope.
    clinical_content = f"clinical-source-{case['label']}".encode()
    clinical = _clinical_attachment(case, clinical_content)
    storage.objects[clinical.storage_key] = clinical_content
    clinical_audit = AsyncMock()
    reads_before_clinical = list(storage.get_calls)
    with patch("app.services.file_attachment_service.audit_service.record", clinical_audit):
        with pytest.raises(AuthorizationError):
            await attachment_service.download(attachment_session, clinical, user)
    assert storage.get_calls == reads_before_clinical
    clinical_audit.assert_not_awaited()
    assert clinical.module == Module.EDC.value
    assert clinical.attachment_type == "Clinical_Attachment"
    assert clinical_content.decode() not in repr(row)
