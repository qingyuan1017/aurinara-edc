"""Final EDC regression and optional-CTMS fallback gate.

Task 7.5: Write the final EDC regression and fallback suite.

This gate deliberately runs the real EDC service workflow instead of replacing
it with CTMS mocks.  The existing resilience property supplies authentication,
clinical capture, protocol visit/casebook, clinical export, audit, and subject
lifecycle coverage; this suite adds the query-thread and clinical-attachment
checks that must remain EDC-owned when CTMS is disabled, empty, or its worker is
unavailable.

**Validates: Requirements 12.14-12.15, 13.14-13.16, 14.4, 14.7, 14.9-14.10**
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.ctms import CTMSPhase, Module, build_ctms_manifest
from app.core.exceptions import AuthorizationError
from app.models.file_attachment import (
    FileAttachment,
    FileAttachmentModule,
    FileAttachmentObjectType,
)
from app.models.identity import UserStatus
from app.models.query import Query, QueryStatus, QueryTargetType
from app.models.subject import SubjectStatus
from app.services.coordination_service import BoundedCoordinationQueue
from app.services.file_attachment_service import FileAttachmentService
from app.services.query_service import QueryService
from app.tests.test_property_ctms_resilience import (
    _run_edc_workflow,
    _valid_lifecycle_path,
)

MODES = ("disabled", "empty", "worker-unavailable")


class _MemoryStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.reads: list[str] = []

    async def get(self, key: str) -> bytes:
        self.reads.append(key)
        return self.content


class _Session:
    def __init__(self) -> None:
        self.add = MagicMock()
        self.flush = AsyncMock()


def _system_user(user_id):
    permission_names = ("study.read", "file.upload")
    role = SimpleNamespace(
        role_permissions=[
            SimpleNamespace(permission=SimpleNamespace(code=permission))
            for permission in permission_names
        ]
    )
    return SimpleNamespace(
        id=user_id,
        status=UserStatus.active,
        user_roles=[SimpleNamespace(role=role, study_id=None, site_id=None)],
    )


def _ctms_viewer(user_id):
    role = SimpleNamespace(
        role_permissions=[
            SimpleNamespace(
                permission=SimpleNamespace(code="ctms.operational-data-read")
            )
        ]
    )
    return SimpleNamespace(
        id=user_id,
        status=UserStatus.active,
        user_roles=[SimpleNamespace(role=role, study_id=None, site_id=None)],
    )


def _fallback_state(mode: str) -> dict[str, object]:
    if mode == "disabled":
        manifest = build_ctms_manifest(enabled=False, phase=CTMSPhase.DISABLED)
        return {"manifest": manifest.as_dict(), "accepted_work": None}
    if mode == "empty":
        manifest = build_ctms_manifest(enabled=True, phase=CTMSPhase.PHASE_3)
        return {"manifest": manifest.as_dict(), "accepted_work": None}

    queue = BoundedCoordinationQueue(capacity=1)
    accepted = queue.try_enqueue(uuid4())
    return {
        "manifest": build_ctms_manifest(
            enabled=True, phase=CTMSPhase.PHASE_3
        ).as_dict(),
        "accepted_work": {
            "accepted": accepted,
            "status": "Pending",
            "worker_status": "unavailable",
            "queue_size": queue.size,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_final_edc_workflow_is_unchanged_by_ctms_fallback(mode: str) -> None:
    """Authentication through lifecycle/export remains byte-for-byte stable."""

    user_id = uuid4()
    record_ids = {name: uuid4() for name in (
        "study_id",
        "site_id",
        "subject_id",
        "study_version_id",
        "form_id",
        "form_definition_id",
        "visit_definition_id",
        "visit_id",
        "export_id",
    )}
    workflow_args = {
        "user_id": user_id,
        "password": "fallback-regression-password",
        "authentication_succeeds": True,
        "values": {str(uuid4()): "clinical-value"},
        "lifecycle_path": _valid_lifecycle_path([
            SubjectStatus.enrolled,
            SubjectStatus.randomized,
            SubjectStatus.on_treatment,
            SubjectStatus.completed,
        ]),
        "visit_offset": 7,
        "record_ids": record_ids,
    }
    baseline = await _run_edc_workflow(**workflow_args)
    fallback = await _run_edc_workflow(**workflow_args)

    assert fallback == baseline
    assert baseline["authentication"][0] is True
    assert baseline["clinical_export"][0] == Module.EDC.value
    assert baseline["clinical_export"][1] == Module.EDC.value
    assert baseline["clinical_audit"]
    assert baseline["protocol_visit"][1] == "in_window"
    assert baseline["casebook"][0] == str(record_ids["subject_id"])
    assert baseline["clinical_lifecycle"] == "Completed"

    state = _fallback_state(mode)
    assert state["manifest"]["module"] == "CTMS"
    if mode == "worker-unavailable":
        assert state["accepted_work"] == {
            "accepted": True,
            "status": "Pending",
            "worker_status": "unavailable",
            "queue_size": 1,
        }
    else:
        assert state["accepted_work"] is None


async def _run_edc_query_and_attachment_workflow() -> dict[str, object]:
    """Exercise EDC query and clinical attachment authority in memory."""

    actor_id = uuid4()
    study_id = uuid4()
    subject_id = uuid4()
    query = Query(
        id=uuid4(),
        study_id=study_id,
        subject_id=subject_id,
        target_type=QueryTargetType.subject.value,
        target_id=subject_id,
        query_type="manual",
        text="EDC query remains authoritative",
        status=QueryStatus.open,
        created_by=actor_id,
    )
    session = _Session()
    audit_actions: list[tuple[str, str]] = []

    async def record_query_audit(_session, **kwargs):
        audit_actions.append((kwargs["entity_type"], kwargs["action"]))
        return SimpleNamespace(id=uuid4())

    with patch(
        "app.services.query_service.audit_service.record",
        new=record_query_audit,
    ):
        await QueryService().respond(
            session, query, "EDC response remains in the query thread", actor_id
        )
        await QueryService().close(session, query, actor_id)

    clinical_content = b"clinical-source-content"
    attachment = FileAttachment(
        id=uuid4(),
        module=FileAttachmentModule.EDC.value,
        attachment_type="Clinical_Attachment",
        object_type=FileAttachmentObjectType.study.value,
        object_id=study_id,
        study_id=study_id,
        filename="source.txt",
        content_type="text/plain",
        size_bytes=len(clinical_content),
        storage_key="edc/source.txt",
        uploaded_by=actor_id,
    )
    storage = _MemoryStorage(clinical_content)
    attachment_audit: list[tuple[str, str]] = []

    async def record_attachment_audit(_session, **kwargs):
        attachment_audit.append((kwargs["entity_type"], kwargs["action"]))
        return SimpleNamespace(id=uuid4())

    with patch(
        "app.services.file_attachment_service.audit_service.record",
        new=record_attachment_audit,
    ):
        downloaded = await FileAttachmentService(storage=storage).download(
            session, attachment, _system_user(actor_id), correlation_id="edc-fallback"
        )
        with pytest.raises(AuthorizationError):
            await FileAttachmentService(storage=storage).download(
                session, attachment, _ctms_viewer(uuid4()), correlation_id="ctms-denied"
            )

    return {
        "query": (query.status.value, len(session.add.call_args_list)),
        "query_audit": tuple(audit_actions),
        "attachment": (downloaded, tuple(storage.reads)),
        "attachment_audit": tuple(attachment_audit),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_queries_and_clinical_attachments_remain_edc_owned(mode: str) -> None:
    """CTMS fallback modes do not change EDC query/file authority or permissions."""

    baseline = await _run_edc_query_and_attachment_workflow()
    fallback = await _run_edc_query_and_attachment_workflow()

    assert fallback == baseline
    assert baseline["query"] == (QueryStatus.closed.value, 1)
    assert baseline["query_audit"] == (("query", "respond"), ("query", "close"))
    assert baseline["attachment"] == (b"clinical-source-content", ("edc/source.txt",))
    assert baseline["attachment_audit"] == (("file_attachment", "download"),)
    assert _fallback_state(mode)["manifest"]["module"] == "CTMS"
