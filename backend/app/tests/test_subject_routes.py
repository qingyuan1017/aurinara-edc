"""Integration tests for subject routes.

Tests cover:
  - GET    /studies/{study_id}/subjects            list (Req 7.1, 21.2)
  - POST   /studies/{study_id}/subjects            create (Req 7.1)
  - GET    /subjects/{subject_id}                  get (Req 7.1)
  - PATCH  /subjects/{subject_id}                  update (Req 7.6)
  - POST   /subjects/{subject_id}/screen-fail      transition (Req 7.3)
  - POST   /subjects/{subject_id}/randomize        transition (Req 7.3)
  - POST   /subjects/{subject_id}/terminate        transition (Req 7.3)
  - GET    /subjects/{subject_id}/casebook         casebook (Req 7.5)
  - Permission enforcement (Req 2.2, 2.3, 21.1)

Uses an in-memory SQLite database and HTTPX async client against the app.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # Create only the tables needed by the subject routes. The full metadata
    # includes Postgres-only JSONB columns (form metadata) that SQLite cannot
    # render, so we restrict creation to the relevant tables.
    from app.models.audit import AuditEvent
    from app.models.identity import (
        Permission as PermissionModel,
    )
    from app.models.identity import (
        Role as RoleModel,
    )
    from app.models.identity import (
        RolePermission as RolePermissionModel,
    )
    from app.models.identity import (
        User as UserModel,
    )
    from app.models.identity import (
        UserRole as UserRoleModel,
    )
    from app.models.site import Site as SiteModel
    from app.models.site import StudySiteUser as StudySiteUserModel
    from app.models.study import Study as StudyModel
    from app.models.study import StudyVersion as StudyVersionModel
    from app.models.subject import Subject as SubjectModel

    tables = [
        m.__table__
        for m in (
            PermissionModel,
            RoleModel,
            RolePermissionModel,
            UserModel,
            UserRoleModel,
            StudyModel,
            StudyVersionModel,
            SiteModel,
            StudySiteUserModel,
            SubjectModel,
            AuditEvent,
        )
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
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
    """Seed a user with subject permissions, a study, published version, and site."""
    # Permissions
    perm_codes = ["subject.read", "subject.create", "subject.update"]
    perms = {}
    for code in perm_codes:
        p = Permission(id=uuid.uuid4(), code=code, description=code)
        db_session.add(p)
        perms[code] = p
    await db_session.flush()

    # System-scope role with all subject permissions
    role = Role(id=uuid.uuid4(), name="Sys", scope_level="system", is_system=True)
    db_session.add(role)
    await db_session.flush()
    for p in perms.values():
        db_session.add(RolePermission(role_id=role.id, permission_id=p.id))
    await db_session.flush()

    # User
    user = User(
        id=uuid.uuid4(),
        email="coordinator@example.com",
        password_hash=hash_password("pw"),
        first_name="Co",
        last_name="Ordinator",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()

    # System-scope assignment (study_id/site_id None)
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    await db_session.flush()

    # Study + published version + site
    study = Study(
        id=uuid.uuid4(),
        study_code="STUDY-001",
        title="Test Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    db_session.add(study)
    await db_session.flush()

    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=user.id,
        created_at=datetime.now(UTC),
    )
    db_session.add(version)

    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Test Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    db_session.add(site)
    await db_session.flush()

    return {
        "user": user,
        "study": study,
        "version": version,
        "site": site,
    }


@pytest.fixture
async def subject(db_session: AsyncSession, seeded: dict) -> Subject:
    """Persist a subject in Screening status."""
    subj = Subject(
        id=uuid.uuid4(),
        study_id=seeded["study"].id,
        site_id=seeded["site"].id,
        study_version_id=seeded["version"].id,
        subject_number="101-0001",
        status=SubjectStatus.screening,
        created_by=seeded["user"].id,
        created_at=datetime.now(UTC),
    )
    db_session.add(subj)
    await db_session.flush()
    return subj


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


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# Create / list
# ---------------------------------------------------------------------------


class TestCreateSubjectRoute:
    async def test_create_subject_success(self, client, seeded):
        resp = await client.post(
            f"/api/v1/studies/{seeded['study'].id}/subjects",
            json={"site_id": str(seeded["site"].id)},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["study_id"] == str(seeded["study"].id)
        assert data["site_id"] == str(seeded["site"].id)
        assert data["status"] == "Screening"
        assert data["subject_number"] == "101-0001"

    async def test_create_subject_requires_auth(self, client, seeded):
        resp = await client.post(
            f"/api/v1/studies/{seeded['study'].id}/subjects",
            json={"site_id": str(seeded["site"].id)},
        )
        assert resp.status_code == 401


class TestListSubjectsRoute:
    async def test_list_subjects_paginated_envelope(self, client, seeded, subject):
        resp = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/subjects",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert {"items", "page", "page_size", "total"} <= data.keys()
        assert data["total"] == 1
        assert data["items"][0]["id"] == str(subject.id)

    async def test_list_subjects_status_filter(self, client, seeded, subject):
        resp = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/subjects",
            params={"status": "Randomized"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_list_subjects_site_filter(self, client, seeded, subject):
        resp = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/subjects",
            params={"site_id": str(seeded["site"].id)},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# Get / update
# ---------------------------------------------------------------------------


class TestGetSubjectRoute:
    async def test_get_subject_success(self, client, seeded, subject):
        resp = await client.get(
            f"/api/v1/subjects/{subject.id}", headers=_auth(seeded["user"])
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == str(subject.id)

    async def test_get_subject_not_found(self, client, seeded):
        resp = await client.get(
            f"/api/v1/subjects/{uuid.uuid4()}", headers=_auth(seeded["user"])
        )
        assert resp.status_code == 404


class TestUpdateSubjectRoute:
    async def test_update_subject_number(self, client, seeded, subject):
        resp = await client.patch(
            f"/api/v1/subjects/{subject.id}",
            json={"subject_number": "101-9999"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["subject_number"] == "101-9999"

    async def test_update_subject_empty_body_noop(self, client, seeded, subject):
        resp = await client.patch(
            f"/api/v1/subjects/{subject.id}",
            json={},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["subject_number"] == "101-0001"


# ---------------------------------------------------------------------------
# Transition endpoints (Req 7.3)
# ---------------------------------------------------------------------------


class TestTransitionRoutes:
    async def test_screen_fail(self, client, seeded, subject):
        resp = await client.post(
            f"/api/v1/subjects/{subject.id}/screen-fail",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Screen Failed"

    async def test_randomize_illegal_from_screening(self, client, seeded, subject):
        # Screening cannot go directly to Randomized
        resp = await client.post(
            f"/api/v1/subjects/{subject.id}/randomize",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 400

    async def test_terminate_illegal_from_screening(self, client, seeded, subject):
        resp = await client.post(
            f"/api/v1/subjects/{subject.id}/terminate",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Casebook (Req 7.5)
# ---------------------------------------------------------------------------


class TestCasebookRoute:
    async def test_get_casebook(self, client, seeded, subject):
        resp = await client.get(
            f"/api/v1/subjects/{subject.id}/casebook",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject_id"] == str(subject.id)
        assert data["subject_number"] == subject.subject_number
        assert data["visits"] == []


# ---------------------------------------------------------------------------
# Permission enforcement (Req 2.2, 2.3)
# ---------------------------------------------------------------------------


class TestSubjectPermissionEnforcement:
    async def test_no_permission_forbidden(
        self, client, db_session, seeded, subject
    ):
        """A user without subject permissions gets 403."""
        nobody = User(
            id=uuid.uuid4(),
            email="nobody@example.com",
            password_hash=hash_password("pw"),
            first_name="No",
            last_name="Body",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(nobody)
        await db_session.flush()

        resp = await client.get(
            f"/api/v1/subjects/{subject.id}", headers=_auth(nobody)
        )
        assert resp.status_code == 403
