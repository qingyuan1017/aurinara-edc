"""API tests for electronic signature routes."""

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
from app.models.identity import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.models.signature import Signature
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
    permission = Permission(id=uuid.uuid4(), code="signature.sign", description="Sign")
    read_permission = Permission(id=uuid.uuid4(), code="form.read", description="Read forms")
    role = Role(id=uuid.uuid4(), name="Investigator", scope_level="system", is_system=True)
    db_session.add_all([permission, read_permission, role])
    await db_session.flush()
    db_session.add_all([
        RolePermission(role_id=role.id, permission_id=permission.id),
        RolePermission(role_id=role.id, permission_id=read_permission.id),
    ])
    user = User(
        id=uuid.uuid4(), email="pi@example.com", password_hash=hash_password("correct-password"),
        first_name="Principal", last_name="Investigator", status=UserStatus.active,
        mfa_enabled=False, last_activity=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))

    study = Study(id=uuid.uuid4(), study_code="SIG-001", title="Signature Study", status=StudyStatus.active, created_by=user.id, created_at=datetime.now(UTC))
    version = StudyVersion(id=uuid.uuid4(), study_id=study.id, version_number="1.0", status=StudyVersionStatus.published, published_at=datetime.now(UTC), published_by=user.id, created_at=datetime.now(UTC))
    site = Site(id=uuid.uuid4(), study_id=study.id, site_number="001", name="Signature Site", status=SiteStatus.active, created_at=datetime.now(UTC))
    subject = Subject(id=uuid.uuid4(), study_id=study.id, site_id=site.id, study_version_id=version.id, subject_number="SIG-001", status=SubjectStatus.enrolled, created_by=user.id, created_at=datetime.now(UTC))
    form_definition = FormDefinition(id=uuid.uuid4(), study_version_id=version.id, name="Vitals", form_code="VS", display_order=1, created_at=datetime.now(UTC))
    db_session.add_all([study, version, site, subject, form_definition])
    await db_session.flush()
    form_instance = FormInstance(id=uuid.uuid4(), subject_id=subject.id, form_definition_id=form_definition.id, status=FormInstanceStatus.submitted, data_jsonb={"weight": "70"}, created_at=datetime.now(UTC))
    db_session.add(form_instance)
    await db_session.flush()
    return {"user": user, "subject": subject, "form_instance": form_instance}


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.asyncio
async def test_signature_routes_reauthenticate_audit_and_list(client, seeded, db_session):
    headers = auth(seeded["user"])
    form_response = await client.post(
        f"/api/v1/form-instances/{seeded['form_instance'].id}/sign",
        json={"meaning": "I attest the form data is accurate.", "password": "correct-password"},
        headers=headers,
    )
    assert form_response.status_code == 201
    form_signature = form_response.json()
    assert form_signature["status"] == "valid"
    assert len(form_signature["data_hash"]) == 64

    subject_response = await client.post(
        f"/api/v1/subjects/{seeded['subject'].id}/sign",
        json={"meaning": "I attest the subject record.", "password": "correct-password"},
        headers=headers,
    )
    assert subject_response.status_code == 201

    listed = await client.get(
        f"/api/v1/subjects/{seeded['subject'].id}/signatures",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert {item["object_type"] for item in listed.json()["items"]} == {"form", "subject"}

    events = (await db_session.execute(select(AuditEvent).where(AuditEvent.entity_type == "signature"))).scalars().all()
    assert len(events) == 2
    assert {event.action for event in events} == {"sign"}


@pytest.mark.asyncio
async def test_signature_route_rejects_failed_reauthentication(client, seeded, db_session):
    response = await client.post(
        f"/api/v1/subjects/{seeded['subject'].id}/sign",
        json={"meaning": "I attest this record.", "password": "wrong-password"},
        headers=auth(seeded["user"]),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AuthenticationError"
    assert (await db_session.execute(select(Signature))).scalars().all() == []


@pytest.mark.asyncio
async def test_signature_routes_require_signature_permission(client, seeded, db_session):
    read_only = User(
        id=uuid.uuid4(), email="reader@example.com", password_hash=hash_password("reader-password"),
        first_name="Read", last_name="Only", status=UserStatus.active,
        mfa_enabled=False, last_activity=datetime.now(UTC),
    )
    read_role = Role(id=uuid.uuid4(), name="Reader", scope_level="system", is_system=True)
    read_permission = (await db_session.execute(select(Permission).where(Permission.code == "form.read"))).scalar_one()
    db_session.add_all([read_only, read_role])
    await db_session.flush()
    db_session.add_all([
        UserRole(user_id=read_only.id, role_id=read_role.id),
        RolePermission(role_id=read_role.id, permission_id=read_permission.id),
    ])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/subjects/{seeded['subject'].id}/sign",
        json={"meaning": "I attest this record.", "password": "reader-password"},
        headers=auth(read_only),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AuthorizationError"
