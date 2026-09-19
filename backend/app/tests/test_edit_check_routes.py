"""Focused route tests for task 19.5 edit-check endpoints."""

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
from app.models.edit_check import EditCheck, ValidationResult
from app.models.form_data import FormInstance
from app.models.form_metadata import FormDefinition
from app.models.identity import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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
    permission = Permission(
        id=uuid.uuid4(), code="editcheck.configure", description="Configure edit checks"
    )
    role = Role(
        id=uuid.uuid4(), name="Data Manager", scope_level="system", is_system=True
    )
    user = User(
        id=uuid.uuid4(),
        email="edit-checks@example.test",
        password_hash=hash_password("pw"),
        first_name="Edit",
        last_name="Checks",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([permission, role, user])
    await db_session.flush()
    db_session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=permission.id),
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )

    study = Study(
        id=uuid.uuid4(),
        study_code="EC-001",
        title="Edit Check Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Test Site",
        status=SiteStatus.active,
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
        name="Demographics",
        form_code="DM",
        display_order=1,
        is_repeating=False,
        created_at=datetime.now(UTC),
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        data_jsonb={"age": 21},
        created_at=datetime.now(UTC),
    )
    db_session.add_all(
        [study, version, site, subject, form_definition, form_instance]
    )
    await db_session.flush()
    return {
        "user": user,
        "study": study,
        "version": version,
        "form_instance": form_instance,
    }


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(
            bind=async_engine, class_=AsyncSession, expire_on_commit=False
        )
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


RULE = {"field": "age", "operator": ">", "value": 18}


class TestEditCheckRoutes:
    async def test_crud_and_study_version_lookup(self, client, seeded, db_session):
        headers = auth(seeded["user"])
        created = await client.post(
            f"/api/v1/studies/{seeded['study'].id}/edit-checks",
            params={"study_version_id": str(seeded["version"].id)},
            json={"name": "Adult age", "rule_json": RULE, "severity": "warning"},
            headers=headers,
        )
        assert created.status_code == 201
        check_id = created.json()["id"]
        assert created.json()["study_version_id"] == str(seeded["version"].id)

        listed = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/edit-checks", headers=headers
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [check_id]

        fetched = await client.get(f"/api/v1/edit-checks/{check_id}", headers=headers)
        assert fetched.status_code == 200

        patched = await client.patch(
            f"/api/v1/edit-checks/{check_id}",
            json={"description": "Updated description"},
            headers=headers,
        )
        assert patched.status_code == 200
        assert patched.json()["description"] == "Updated description"
        event = (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "edit_check",
                    AuditEvent.entity_id == uuid.UUID(check_id),
                    AuditEvent.action == "update",
                )
            )
        ).scalar_one()
        assert event.actor_id == seeded["user"].id

    async def test_test_endpoint_evaluates_without_persistence(self, client, seeded, db_session):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Adult age",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/edit-checks/{check.id}/test",
            json={"sample_data": {"age": 21}},
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        assert response.json()["outcome"] is True
        assert response.json()["persisted"] is False
        assert (
            await db_session.execute(select(ValidationResult))
        ).scalars().all() == []

    async def test_run_evaluates_forms_and_persists_failures(self, client, seeded, db_session):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Adult age",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/studies/{seeded['study'].id}/edit-checks/run",
            json={"study_version_id": str(seeded["version"].id)},
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        assert response.json()["evaluated_form_instances"] == 1
        assert response.json()["failed_checks"] == 1
        assert len(response.json()["results"]) == 1
        persisted = (await db_session.execute(select(ValidationResult))).scalars().all()
        assert len(persisted) == 1

    async def test_routes_enforce_server_side_authorization(self, client, db_session, seeded):
        unauthorized = User(
            id=uuid.uuid4(),
            email="unauthorized@example.test",
            password_hash=hash_password("pw"),
            first_name="No",
            last_name="Access",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(unauthorized)
        await db_session.flush()

        response = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/edit-checks",
            headers=auth(unauthorized),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"

    async def test_invalid_dsl_uses_standard_error_envelope(self, client, seeded):
        response = await client.post(
            f"/api/v1/studies/{seeded['study'].id}/edit-checks",
            json={
                "name": "Unsafe rule",
                "rule_json": {"field": "age", "operator": "exec", "value": "x"},
                "severity": "warning",
            },
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ValidationError"
        assert response.json()["error"]["details"]["path"] == "$.operator"
