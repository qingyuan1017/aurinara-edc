"""Focused API tests for repeating Form_Record routes.

Validates Requirements 11.1-11.4 and 21.1: route permissions, sequence
allocation, edit, soft-delete, restore, and standard not-found handling.
"""

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
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.form_record import FormRecord
from app.models.identity import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # Importing app.models registers every model with the shared metadata. The
    # SQLite variants of JSONB columns make the complete graph testable here.
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    session_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict:
    permissions = {
        code: Permission(id=uuid.uuid4(), code=code, description=code)
        for code in ("form.enter",)
    }
    db_session.add_all(permissions.values())
    await db_session.flush()

    role = Role(
        id=uuid.uuid4(),
        name="Records Coordinator",
        scope_level="system",
        is_system=True,
    )
    db_session.add(role)
    await db_session.flush()
    db_session.add(
        RolePermission(role_id=role.id, permission_id=permissions["form.enter"].id)
    )

    user = User(
        id=uuid.uuid4(),
        email="records@example.com",
        password_hash=hash_password("pw"),
        first_name="Records",
        last_name="User",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([UserRole(user_id=user.id, role_id=role.id)])

    study = Study(
        id=uuid.uuid4(),
        study_code="RECORDS-001",
        title="Records Route Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=user.id,
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Records Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([study, version, site])
    await db_session.flush()

    subject = Subject(
        id=uuid.uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="101-0001",
        status=SubjectStatus.screening,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Adverse Events",
        form_code="AE",
        display_order=1,
        is_repeating=True,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([subject, form_definition])
    await db_session.flush()

    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        status=FormInstanceStatus.in_progress,
        created_at=datetime.now(UTC),
    )
    db_session.add(form_instance)
    await db_session.flush()

    return {"user": user, "subject": subject, "form_instance": form_instance}


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

    application = create_app()

    async def _override_get_db():
        session_factory = async_sessionmaker(
            bind=async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


class TestRecordsRoutes:
    async def test_add_record_assigns_sequence_and_audits(
        self, client, seeded, db_session: AsyncSession
    ):
        response = await client.post(
            f"/api/v1/form-instances/{seeded['form_instance'].id}/records",
            json={"values": {"term": "Headache"}},
            headers=_auth(seeded["user"]),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["sequence_number"] == 1
        assert data["data_jsonb"] == {"term": "Headache"}

        event = (
            (await db_session.execute(
                select(AuditEvent).where(AuditEvent.entity_id == uuid.UUID(data["id"]))
            ))
            .scalars()
            .one()
        )
        assert event.action == "create"
        assert event.entity_type == "form_record"

    async def test_patch_delete_and_restore_record(self, client, seeded, db_session):
        record = FormRecord(
            id=uuid.uuid4(),
            form_instance_id=seeded["form_instance"].id,
            sequence_number=1,
            data_jsonb={"term": "Headache"},
            created_at=datetime.now(UTC),
        )
        db_session.add(record)
        await db_session.flush()

        patched = await client.patch(
            f"/api/v1/records/{record.id}",
            json={"values": {"term": "Resolved"}},
            headers=_auth(seeded["user"]),
        )
        assert patched.status_code == 200
        assert patched.json()["data_jsonb"] == {"term": "Resolved"}

        deleted = await client.request(
            "DELETE",
            f"/api/v1/records/{record.id}",
            json={"reason": "Entered in error"},
            headers=_auth(seeded["user"]),
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted_by"] == str(seeded["user"].id)
        assert deleted.json()["deletion_reason"] == "Entered in error"

        restored = await client.post(
            f"/api/v1/records/{record.id}/restore",
            headers=_auth(seeded["user"]),
        )
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None
        assert restored.json()["deletion_reason"] is None

    async def test_record_routes_require_authentication(self, client, seeded):
        response = await client.post(
            f"/api/v1/form-instances/{seeded['form_instance'].id}/records",
            json={"values": {}},
        )
        assert response.status_code == 401

    async def test_record_not_found_uses_standard_error(self, client, seeded):
        response = await client.patch(
            f"/api/v1/records/{uuid.uuid4()}",
            json={"values": {}},
            headers=_auth(seeded["user"]),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NotFoundError"
