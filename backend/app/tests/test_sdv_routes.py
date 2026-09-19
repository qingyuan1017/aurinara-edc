"""Focused integration tests for SDV routes (Requirements 14.1-14.3, 21.1)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.sdv import SDVStatus
from app.models.site import Site, SiteStatus, StudySiteUser
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitDefinition, VisitInstance


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
            VisitDefinition,
            VisitInstance,
            FormDefinition,
            FormSection,
            FieldDefinition,
            FormInstance,
            FieldValue,
            SDVStatus,
            AuditEvent,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
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
async def seeded(db_session: AsyncSession):
    permissions = {}
    for code in ("sdv.manage",):
        permission = Permission(id=uuid.uuid4(), code=code, description=code)
        db_session.add(permission)
        permissions[code] = permission
    await db_session.flush()

    role = Role(
        id=uuid.uuid4(), name="CRA", scope_level="system", is_system=True
    )
    db_session.add(role)
    await db_session.flush()
    db_session.add(
        RolePermission(role_id=role.id, permission_id=permissions["sdv.manage"].id)
    )

    user = User(
        id=uuid.uuid4(),
        email="cra@example.test",
        password_hash=hash_password("pw"),
        first_name="Clinical",
        last_name="Researcher",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))

    study = Study(
        id=uuid.uuid4(),
        study_code="SDV-001",
        title="SDV Study",
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
        name="SDV Site",
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
        status=SubjectStatus.enrolled,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    form = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Vitals",
        form_code="VS",
        display_order=1,
        is_repeating=False,
        created_at=datetime.now(UTC),
    )
    section = FormSection(
        id=uuid.uuid4(),
        form_definition_id=form.id,
        name="Vitals",
        display_order=1,
    )
    field = FieldDefinition(
        id=uuid.uuid4(),
        form_section_id=section.id,
        label="Pulse",
        variable_name="pulse",
        control_type="integer",
        data_type="integer",
        is_required=False,
        display_order=1,
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form.id,
        status=FormInstanceStatus.in_progress,
        created_at=datetime.now(UTC),
    )
    field_value = FieldValue(
        id=uuid.uuid4(),
        form_instance_id=form_instance.id,
        field_definition_id=field.id,
        value="72",
        created_at=datetime.now(UTC),
    )
    db_session.add_all([subject, form, section, field, form_instance, field_value])
    await db_session.flush()

    return {
        "user": user,
        "study": study,
        "subject": subject,
        "form_instance": form_instance,
        "field_value": field_value,
    }


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

    application = create_app()

    async def override_get_db():
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

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


class TestSDVRoutes:
    async def test_field_sdv_and_unsdv_round_trip(self, client, seeded):
        field_id = seeded["field_value"].id
        headers = auth(seeded["user"])

        verified = await client.post(f"/api/v1/fields/{field_id}/sdv", headers=headers)
        assert verified.status_code == 200
        assert verified.json()["scope_type"] == "field"
        assert verified.json()["scope_id"] == str(field_id)
        assert verified.json()["is_verified"] is True
        assert verified.json()["verified_by"] == str(seeded["user"].id)
        assert verified.headers["x-request-id"]

        cleared = await client.post(f"/api/v1/fields/{field_id}/unsdv", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()["is_verified"] is False
        assert cleared.json()["verified_by"] is None

    async def test_form_instance_sdv(self, client, seeded):
        response = await client.post(
            f"/api/v1/form-instances/{seeded['form_instance'].id}/sdv",
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scope_type"] == "form"
        assert data["scope_id"] == str(seeded["form_instance"].id)
        assert data["is_verified"] is True

    async def test_study_progress_counts_field_and_form_targets(self, client, seeded):
        headers = auth(seeded["user"])
        await client.post(
            f"/api/v1/fields/{seeded['field_value'].id}/sdv", headers=headers
        )
        await client.post(
            f"/api/v1/form-instances/{seeded['form_instance'].id}/sdv",
            headers=headers,
        )

        response = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/sdv-progress",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"verified": 2, "not_verified": 1}

    async def test_target_not_found_uses_error_envelope(self, client, seeded):
        response = await client.post(
            f"/api/v1/form-instances/{uuid.uuid4()}/sdv",
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 404
        assert set(response.json()) == {"error"}
        assert {"code", "message", "details"} <= response.json()["error"].keys()

    async def test_sdv_requires_target_scope_permission(
        self, client, db_session, seeded
    ):
        user = User(
            id=uuid.uuid4(),
            email="read-only@example.test",
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
            f"/api/v1/form-instances/{seeded['form_instance'].id}/sdv",
            headers=auth(user),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"
