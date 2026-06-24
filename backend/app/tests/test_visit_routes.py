"""Integration tests for visit routes.

Tests cover:
  - GET   /subjects/{subject_id}/visits               list (Req 8.3, 8.5, 21.1)
  - POST  /subjects/{subject_id}/visits/unscheduled   create unscheduled (Req 8.4)
  - GET   /visits/{visit_id}                          get (Req 8.3)
  - PATCH /visits/{visit_id}                           record date (Req 8.3)
  - POST  /visits/{visit_id}/mark-missed              mark missed (Req 8.5)
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
from app.models.visit import VisitDefinition, VisitInstance, VisitInstanceStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
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
    from app.models.visit import VisitDefinition as VisitDefinitionModel
    from app.models.visit import VisitInstance as VisitInstanceModel

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
            VisitDefinitionModel,
            VisitInstanceModel,
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
    perm_codes = ["subject.read", "subject.update"]
    perms = {}
    for code in perm_codes:
        p = Permission(id=uuid.uuid4(), code=code, description=code)
        db_session.add(p)
        perms[code] = p
    await db_session.flush()

    role = Role(id=uuid.uuid4(), name="Sys", scope_level="system", is_system=True)
    db_session.add(role)
    await db_session.flush()
    for p in perms.values():
        db_session.add(RolePermission(role_id=role.id, permission_id=p.id))
    await db_session.flush()

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

    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    await db_session.flush()

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

    return {"user": user, "study": study, "version": version, "site": site}


@pytest.fixture
async def subject(db_session: AsyncSession, seeded: dict) -> Subject:
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
async def visit_definition(db_session: AsyncSession, seeded: dict) -> VisitDefinition:
    """A visit definition with a target day and window bounds for status tests."""
    vd = VisitDefinition(
        id=uuid.uuid4(),
        study_version_id=seeded["version"].id,
        name="Week 4",
        visit_number=2,
        visit_type="scheduled",
        target_day=28,
        window_before=3,
        window_after=3,
        display_order=2,
        is_required=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(vd)
    await db_session.flush()
    return vd


@pytest.fixture
async def visit_instance(
    db_session: AsyncSession, subject: Subject, visit_definition: VisitDefinition
) -> VisitInstance:
    inst = VisitInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        visit_definition_id=visit_definition.id,
        name="Week 4",
        status=VisitInstanceStatus.scheduled,
        created_at=datetime.now(UTC),
    )
    db_session.add(inst)
    await db_session.flush()
    return inst


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
# List visits (Req 8.3, 8.5)
# ---------------------------------------------------------------------------


class TestListSubjectVisitsRoute:
    async def test_list_visits_success(self, client, seeded, subject, visit_instance):
        resp = await client.get(
            f"/api/v1/subjects/{subject.id}/visits",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == str(visit_instance.id)
        assert data[0]["subject_id"] == str(subject.id)

    async def test_list_visits_empty(self, client, seeded, subject):
        resp = await client.get(
            f"/api/v1/subjects/{subject.id}/visits",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_visits_subject_not_found(self, client, seeded):
        resp = await client.get(
            f"/api/v1/subjects/{uuid.uuid4()}/visits",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 404

    async def test_list_visits_requires_auth(self, client, subject):
        resp = await client.get(f"/api/v1/subjects/{subject.id}/visits")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Create unscheduled visit (Req 8.4)
# ---------------------------------------------------------------------------


class TestCreateUnscheduledVisitRoute:
    async def test_create_unscheduled_success(self, client, seeded, subject):
        resp = await client.post(
            f"/api/v1/subjects/{subject.id}/visits/unscheduled",
            json={"name": "Unscheduled AE Visit", "visit_date": "2024-06-01"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Unscheduled AE Visit"
        assert data["status"] == "unscheduled"
        assert data["visit_definition_id"] is None
        assert data["subject_id"] == str(subject.id)

    async def test_create_unscheduled_subject_not_found(self, client, seeded):
        resp = await client.post(
            f"/api/v1/subjects/{uuid.uuid4()}/visits/unscheduled",
            json={"name": "X"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Get visit (Req 8.3)
# ---------------------------------------------------------------------------


class TestGetVisitRoute:
    async def test_get_visit_success(self, client, seeded, visit_instance):
        resp = await client.get(
            f"/api/v1/visits/{visit_instance.id}",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == str(visit_instance.id)

    async def test_get_visit_not_found(self, client, seeded):
        resp = await client.get(
            f"/api/v1/visits/{uuid.uuid4()}",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Record visit date (Req 8.3)
# ---------------------------------------------------------------------------


class TestRecordVisitDateRoute:
    async def test_record_visit_date_in_window(self, client, seeded, visit_instance):
        # baseline 2024-01-01, target_day=28 -> 2024-01-29; window ±3 days.
        # Visit on 2024-01-29 (offset 28) is in_window.
        resp = await client.patch(
            f"/api/v1/visits/{visit_instance.id}",
            json={"visit_date": "2024-01-29", "baseline_date": "2024-01-01"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visit_date"] == "2024-01-29"
        assert data["window_status"] == "in_window"
        assert data["status"] == "in_window"

    async def test_record_visit_date_after_window(
        self, client, seeded, visit_instance
    ):
        # Offset 40 days > 28+3 -> after_window.
        resp = await client.patch(
            f"/api/v1/visits/{visit_instance.id}",
            json={"visit_date": "2024-02-10", "baseline_date": "2024-01-01"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["window_status"] == "after_window"

    async def test_record_visit_date_not_found(self, client, seeded):
        resp = await client.patch(
            f"/api/v1/visits/{uuid.uuid4()}",
            json={"visit_date": "2024-01-29"},
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Mark missed (Req 8.5)
# ---------------------------------------------------------------------------


class TestMarkMissedRoute:
    async def test_mark_missed_success(self, client, seeded, visit_instance):
        resp = await client.post(
            f"/api/v1/visits/{visit_instance.id}/mark-missed",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "missed"

    async def test_mark_missed_not_found(self, client, seeded):
        resp = await client.post(
            f"/api/v1/visits/{uuid.uuid4()}/mark-missed",
            headers=_auth(seeded["user"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Permission enforcement (Req 2.2, 2.3)
# ---------------------------------------------------------------------------


class TestVisitPermissionEnforcement:
    async def test_no_permission_forbidden(
        self, client, db_session, seeded, visit_instance
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
            f"/api/v1/visits/{visit_instance.id}", headers=_auth(nobody)
        )
        assert resp.status_code == 403

    async def test_mark_missed_requires_update_permission(
        self, client, db_session, seeded, visit_instance
    ):
        """A read-only user (subject.read only) cannot mark a visit missed."""
        from sqlalchemy import select

        from app.models.identity import Permission as PermissionModel

        # Read-only role bound to the existing subject.read permission only.
        ro_role = Role(
            id=uuid.uuid4(), name="RO", scope_level="system", is_system=True
        )
        db_session.add(ro_role)
        await db_session.flush()

        read_perm = (
            (
                await db_session.execute(
                    select(PermissionModel).where(
                        PermissionModel.code == "subject.read"
                    )
                )
            )
            .scalars()
            .first()
        )
        db_session.add(
            RolePermission(role_id=ro_role.id, permission_id=read_perm.id)
        )

        ro_user = User(
            id=uuid.uuid4(),
            email="ro@example.com",
            password_hash=hash_password("pw"),
            first_name="Read",
            last_name="Only",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(ro_user)
        await db_session.flush()
        db_session.add(UserRole(user_id=ro_user.id, role_id=ro_role.id))
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/visits/{visit_instance.id}/mark-missed",
            headers=_auth(ro_user),
        )
        assert resp.status_code == 403
