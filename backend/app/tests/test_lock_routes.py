"""Focused API tests for freeze and lock routes (Requirements 16.1, 16.2, 16.4)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import (
    Codelist,
    CodelistItem,
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.identity import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.models.lock import FreezeLock
from app.models.site import Site, StudySiteUser
from app.models.study import Study, StudyStatus, StudyVersion
from app.models.subject import Subject, SubjectStatus


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    tables = [
        model.__table__
        for model in (
            Permission,
            Role,
            RolePermission,
            User,
            UserRole,
            Study,
            StudyVersion,
            Site,
            StudySiteUser,
            Subject,
            FormDefinition,
            FormSection,
            FieldDefinition,
            Codelist,
            CodelistItem,
            FormInstance,
            FieldValue,
            FreezeLock,
            AuditEvent,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession):
    permission = Permission(id=uuid.uuid4(), code="lock.manage", description="Manage locks")
    role = Role(
        id=uuid.uuid4(),
        name="Data Manager",
        scope_level="system",
        is_system=True,
    )
    user = User(
        id=uuid.uuid4(),
        email="manager@example.test",
        password_hash=hash_password("pw"),
        first_name="Data",
        last_name="Manager",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([permission, role, user])
    await db_session.flush()
    db_session.add_all([
        RolePermission(role_id=role.id, permission_id=permission.id),
        UserRole(user_id=user.id, role_id=role.id),
    ])

    study = Study(
        id=uuid.uuid4(),
        study_code="LOCK-001",
        title="Lock Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status="published",
        published_by=user.id,
        published_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Lock Site",
        created_at=datetime.now(UTC),
    )
    subject = Subject(
        id=uuid.uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="101-0001",
        status=SubjectStatus.enrolled,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Lock Form",
        form_code="LOCK",
        display_order=1,
        is_repeating=False,
        created_at=datetime.now(UTC),
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([study, version, site, subject, form_definition, form_instance])
    await db_session.flush()
    return {"user": user, "study": study, "subject": subject, "form": form_instance}


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


class TestLockRoutes:
    async def test_form_freeze_and_unfreeze_require_reason_and_audit(self, client, db_session, seeded):
        headers = auth(seeded["user"])
        freeze = await client.post(
            f"/api/v1/form-instances/{seeded['form'].id}/freeze", headers=headers
        )
        assert freeze.status_code == 200
        assert freeze.json()["lock_type"] == "freeze"
        assert freeze.json()["is_active"] is True

        missing_reason = await client.post(
            f"/api/v1/form-instances/{seeded['form'].id}/unfreeze",
            json={"reason": "  "},
            headers=headers,
        )
        assert missing_reason.status_code == 422
        assert missing_reason.json()["error"]["code"] == "ValidationError"

        unfreeze = await client.post(
            f"/api/v1/form-instances/{seeded['form'].id}/unfreeze",
            json={"reason": "Data review complete"},
            headers=headers,
        )
        assert unfreeze.status_code == 200
        assert unfreeze.json()["is_active"] is False
        assert unfreeze.json()["unlock_reason"] == "Data review complete"

        event = (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "form",
                    AuditEvent.entity_id == seeded["form"].id,
                    AuditEvent.action == "unfreeze",
                )
            )
        ).scalar_one()
        assert event.actor_id == seeded["user"].id
        assert event.reason == "Data review complete"

    async def test_subject_and_study_lock_routes_delegate(self, client, seeded):
        headers = auth(seeded["user"])
        subject_lock = await client.post(
            f"/api/v1/subjects/{seeded['subject'].id}/lock", headers=headers
        )
        assert subject_lock.status_code == 200
        assert subject_lock.json()["object_type"] == "subject"
        assert subject_lock.json()["lock_type"] == "lock"

        study_lock = await client.post(
            f"/api/v1/studies/{seeded['study'].id}/lock", headers=headers
        )
        assert study_lock.status_code == 200
        assert study_lock.json()["object_type"] == "study"
        assert study_lock.json()["lock_type"] == "lock"

    async def test_lock_routes_require_lock_manage_permission(self, client, db_session, seeded):
        user = User(
            id=uuid.uuid4(),
            email="readonly@example.test",
            password_hash=hash_password("pw"),
            first_name="Read",
            last_name="Only",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(user)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/subjects/{seeded['subject'].id}/freeze", headers=auth(user)
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"
