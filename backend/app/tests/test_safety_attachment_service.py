"""Example-based coverage for PV Safety_Attachments (task 6.4).

Feature: pv-safety-module, Task 6.4
Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7

Exercises the SafetyAttachmentService against an in-memory database and a
temp-directory object store so upload validation, storage-failure handling,
download read-access, soft deletion, Closed-case rejection, cross-module
ownership rejection, and the atomic PV safety Audit_Event are covered end to
end. The service reuses the shared ``file_attachments`` table (tagged
``module="PV"``) and the shared object-storage abstraction rather than forking
them.
"""

from __future__ import annotations

from typing import NamedTuple
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.core.database import Base
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.pv import ActorContext
from app.core.storage import LocalObjectStorage
from app.models.audit import AuditEvent
from app.models.file_attachment import (
    FileAttachment,
    FileAttachmentModule,
    FileAttachmentObjectType,
)
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.pv.safety_case import CaseState, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.safety_attachment_service import SafetyAttachmentService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class _RaisingStorage:
    """Object storage that fails every ``put`` to simulate unavailability."""

    def __init__(self) -> None:
        self.put_calls = 0

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.put_calls += 1
        raise OSError("object storage unavailable")

    async def get(self, key: str) -> bytes:  # pragma: no cover - not reached
        raise FileNotFoundError(key)

    async def delete(self, key: str) -> None:  # pragma: no cover - not reached
        return None


def _service(tmp_path) -> SafetyAttachmentService:
    return SafetyAttachmentService(storage=LocalObjectStorage(tmp_path / "store"))


def _actor(user: User) -> ActorContext:
    return ActorContext(
        user_id=user.id, request_id=str(uuid4()), correlation_id=str(uuid4())
    )


class _Seeded(NamedTuple):
    actor: User
    study: Study
    site: Site
    case: SafetyCase


async def _seed(session: AsyncSession, *, state: CaseState = CaseState.OPEN) -> _Seeded:
    actor = User(
        email=f"pv-{uuid4()}@example.test",
        first_name="PV",
        last_name="Associate",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()

    study = Study(study_code=f"PV-{uuid4()}", title="Safety study", created_by=actor.id)
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id, version_number="1.0", status=StudyVersionStatus.published
    )
    session.add(version)
    await session.flush()

    site = Site(study_id=study.id, site_number="001", name="Site A")
    session.add(site)
    await session.flush()

    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="S-001",
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()

    case = SafetyCase(
        case_identifier=f"PV-CASE-{uuid4().hex[:8]}",
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        lifecycle_state=state.value,
        created_by=actor.id,
    )
    session.add(case)
    await session.flush()
    return _Seeded(actor=actor, study=study, site=site, case=case)


async def _grant(session: AsyncSession, user: User, codes, study, site=None) -> None:
    """Assign a role with the given permission codes at study/site scope."""
    role = Role(name=f"role-{uuid4().hex[:8]}", scope_level="study")
    session.add(role)
    await session.flush()
    for code in codes:
        result = await session.execute(select(Permission).where(Permission.code == code))
        permission = result.scalar_one_or_none()
        if permission is None:
            permission = Permission(code=code, description=code)
            session.add(permission)
            await session.flush()
        session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    await session.flush()
    session.add(
        UserRole(
            user_id=user.id,
            role_id=role.id,
            study_id=study.id,
            site_id=site.id if site is not None else None,
        )
    )
    await session.flush()


async def _load_user_with_roles(session: AsyncSession, user_id) -> User:
    """Reload a user with role/permission graph eagerly for scope resolution."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.user_roles)
            .selectinload(UserRole.role)
            .selectinload(Role.role_permissions)
            .selectinload(RolePermission.permission)
        )
    )
    return result.scalar_one()


async def _audit_count(session: AsyncSession, action: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.entity_type == "safety_attachment",
            AuditEvent.action == action,
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Upload (Requirements 15.1, 15.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_persists_pv_attachment_with_audit(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)

    attachment = await service.upload(
        db_session,
        case_id=seed.case.id,
        file=b"safety-source-document",
        actor=_actor(seed.actor),
    )

    assert attachment.module == FileAttachmentModule.PV.value
    assert attachment.attachment_type == "Safety_Attachment"
    assert attachment.object_type == FileAttachmentObjectType.safety.value
    assert attachment.object_id == seed.case.id
    assert attachment.study_id == seed.study.id
    assert attachment.site_id == seed.site.id
    assert attachment.size_bytes == len(b"safety-source-document")
    assert attachment.deleted_at is None
    assert await _audit_count(db_session, "upload") == 1


@pytest.mark.asyncio
async def test_upload_rejects_empty_file_without_storage_or_metadata(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)

    with pytest.raises(ValidationError) as exc:
        await service.upload(
            db_session, case_id=seed.case.id, file=b"", actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "EMPTY_ATTACHMENT"

    # No metadata and no completed-action audit event were persisted.
    count = await db_session.execute(select(func.count()).select_from(FileAttachment))
    assert int(count.scalar_one()) == 0
    assert await _audit_count(db_session, "upload") == 0


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(tmp_path, db_session, monkeypatch):
    seed = await _seed(db_session)
    service = _service(tmp_path)

    # Patch the module limit down so the test does not allocate 100 MB.
    monkeypatch.setattr(
        "app.services.safety_attachment_service._MAX_SAFETY_ATTACHMENT_BYTES", 8
    )
    with pytest.raises(ValidationError) as exc:
        await service.upload(
            db_session, case_id=seed.case.id, file=b"way-too-large", actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "ATTACHMENT_TOO_LARGE"
    count = await db_session.execute(select(func.count()).select_from(FileAttachment))
    assert int(count.scalar_one()) == 0


@pytest.mark.asyncio
async def test_upload_rejects_when_object_storage_unavailable(tmp_path, db_session):
    seed = await _seed(db_session)
    storage = _RaisingStorage()
    service = SafetyAttachmentService(storage=storage)

    with pytest.raises(ServiceUnavailableError) as exc:
        await service.upload(
            db_session, case_id=seed.case.id, file=b"content", actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "OBJECT_STORAGE_UNAVAILABLE"
    assert storage.put_calls == 1

    # No metadata persisted and no completed-action audit event (15.7, 15.4).
    count = await db_session.execute(select(func.count()).select_from(FileAttachment))
    assert int(count.scalar_one()) == 0
    assert await _audit_count(db_session, "upload") == 0


@pytest.mark.asyncio
async def test_upload_rejected_while_case_closed(tmp_path, db_session):
    seed = await _seed(db_session, state=CaseState.CLOSED)
    service = _service(tmp_path)

    with pytest.raises(ConflictError) as exc:
        await service.upload(
            db_session, case_id=seed.case.id, file=b"content", actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "CASE_CLOSED"
    count = await db_session.execute(select(func.count()).select_from(FileAttachment))
    assert int(count.scalar_one()) == 0


@pytest.mark.asyncio
async def test_upload_rejects_unknown_case(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)

    with pytest.raises(NotFoundError):
        await service.upload(
            db_session, case_id=uuid4(), file=b"content", actor=_actor(seed.actor)
        )


# ---------------------------------------------------------------------------
# Download (Requirements 15.2, 15.3, 15.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_returns_content_and_records_audit(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload-bytes", actor=_actor(seed.actor)
    )

    content = await service.download(
        db_session, attachment_id=attachment.id, actor=_actor(seed.actor)
    )
    assert content == b"payload-bytes"
    assert await _audit_count(db_session, "download") == 1


@pytest.mark.asyncio
async def test_download_denied_without_case_read_access(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload", actor=_actor(seed.actor)
    )

    # A user granted only on a different study cannot read this case.
    other_study = Study(study_code=f"OTHER-{uuid4()}", title="Other", created_by=seed.actor.id)
    db_session.add(other_study)
    await db_session.flush()
    reader = User(
        email=f"reader-{uuid4()}@example.test",
        first_name="R",
        last_name="Eader",
        status=UserStatus.active,
    )
    db_session.add(reader)
    await db_session.flush()
    await _grant(db_session, reader, ["safety_case.read"], other_study)
    reader = await _load_user_with_roles(db_session, reader.id)

    with pytest.raises(AuthorizationError):
        await service.download(
            db_session, attachment_id=attachment.id, actor=_actor(reader), user=reader
        )


@pytest.mark.asyncio
async def test_download_allowed_with_case_read_access(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload", actor=_actor(seed.actor)
    )
    reader = User(
        email=f"reader-{uuid4()}@example.test",
        first_name="R",
        last_name="Eader",
        status=UserStatus.active,
    )
    db_session.add(reader)
    await db_session.flush()
    await _grant(db_session, reader, ["safety_case.read"], seed.study)
    reader = await _load_user_with_roles(db_session, reader.id)

    content = await service.download(
        db_session, attachment_id=attachment.id, actor=_actor(reader), user=reader
    )
    assert content == b"payload"


@pytest.mark.asyncio
async def test_download_rejected_after_soft_delete(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload", actor=_actor(seed.actor)
    )
    await service.soft_delete(
        db_session, attachment_id=attachment.id, reason="superseded", actor=_actor(seed.actor)
    )

    with pytest.raises(NotFoundError) as exc:
        await service.download(
            db_session, attachment_id=attachment.id, actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "ATTACHMENT_DELETED"


# ---------------------------------------------------------------------------
# Soft delete (Requirements 15.3, 15.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_retains_metadata_and_reason_with_audit(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload", actor=_actor(seed.actor)
    )

    deleted = await service.soft_delete(
        db_session,
        attachment_id=attachment.id,
        reason="  duplicate upload  ",
        actor=_actor(seed.actor),
    )
    assert deleted.deleted_at is not None
    assert deleted.deleted_by == seed.actor.id
    assert deleted.delete_reason == "duplicate upload"
    assert deleted.retention_state == "soft_deleted"
    # Metadata row is retained (not physically removed).
    count = await db_session.execute(select(func.count()).select_from(FileAttachment))
    assert int(count.scalar_one()) == 1
    assert await _audit_count(db_session, "delete") == 1


@pytest.mark.asyncio
async def test_soft_delete_requires_reason(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload", actor=_actor(seed.actor)
    )

    with pytest.raises(ValidationError) as exc:
        await service.soft_delete(
            db_session, attachment_id=attachment.id, reason="   ", actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "MISSING_DELETE_REASON"


@pytest.mark.asyncio
async def test_soft_delete_twice_conflicts(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)
    attachment = await service.upload(
        db_session, case_id=seed.case.id, file=b"payload", actor=_actor(seed.actor)
    )
    await service.soft_delete(
        db_session, attachment_id=attachment.id, reason="first", actor=_actor(seed.actor)
    )
    with pytest.raises(ConflictError) as exc:
        await service.soft_delete(
            db_session, attachment_id=attachment.id, reason="second", actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "ALREADY_DELETED"


# ---------------------------------------------------------------------------
# Cross-module ownership (Requirement 15.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pv_operation_rejects_edc_clinical_attachment(tmp_path, db_session):
    seed = await _seed(db_session)
    service = _service(tmp_path)

    # A shared row owned by EDC must not be downloadable/deletable via PV.
    clinical = FileAttachment(
        id=uuid4(),
        module=FileAttachmentModule.EDC.value,
        attachment_type="Clinical_Attachment",
        object_type=FileAttachmentObjectType.subject.value,
        object_id=uuid4(),
        study_id=seed.study.id,
        site_id=seed.site.id,
        filename="clinical.pdf",
        content_type="application/pdf",
        size_bytes=10,
        storage_key="files/clinical",
        uploaded_by=seed.actor.id,
    )
    db_session.add(clinical)
    await db_session.flush()

    with pytest.raises(ConflictError) as exc:
        await service.download(
            db_session, attachment_id=clinical.id, actor=_actor(seed.actor)
        )
    assert exc.value.details["reason"] == "NON_PV_ATTACHMENT"

    with pytest.raises(ConflictError):
        await service.soft_delete(
            db_session, attachment_id=clinical.id, reason="x", actor=_actor(seed.actor)
        )
    # EDC row unchanged (not soft-deleted).
    await db_session.refresh(clinical)
    assert clinical.deleted_at is None
