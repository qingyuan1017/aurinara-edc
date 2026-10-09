"""Focused route tests for the Designer cycle-definition list endpoint.

Covers the version-scoped GET surface mounted under
``/api/v1/designer/versions/{version_id}/cycles``: ordered listing and
server-side default-deny authorization (``designer.cycle.read``).
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.designer.cycle_definition import CycleDefinition
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)


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
    read_permission = Permission(
        id=uuid.uuid4(),
        code="designer.cycle.read",
        description="Read cycle definitions",
    )
    role = Role(id=uuid.uuid4(), name="Designer_Role", scope_level="system", is_system=True)
    user = User(
        id=uuid.uuid4(),
        email="cycles@example.test",
        password_hash=hash_password("pw"),
        first_name="Cycle",
        last_name="Designer",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([read_permission, role, user])
    await db_session.flush()
    db_session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=read_permission.id),
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )

    study = Study(
        id=uuid.uuid4(),
        study_code="CD-001",
        title="Cycle Definition Study",
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
    db_session.add_all([study, version])
    await db_session.flush()
    return {"user": user, "study": study, "version": version}


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


class TestCycleDefinitionListRoute:
    async def test_get_returns_cycles_ordered_by_display_order(
        self, client, seeded, db_session
    ):
        later = CycleDefinition(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Cycle 2",
            display_order=2,
            created_at=datetime.now(UTC),
        )
        earlier = CycleDefinition(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Cycle 1",
            display_order=1,
            created_at=datetime.now(UTC),
        )
        db_session.add_all([later, earlier])
        await db_session.flush()

        response = await client.get(
            f"/api/v1/designer/versions/{seeded['version'].id}/cycles",
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == ["Cycle 1", "Cycle 2"]

    async def test_get_default_deny_without_read_permission(
        self, client, db_session, seeded
    ):
        unauthorized = User(
            id=uuid.uuid4(),
            email="no-cycle-read@example.test",
            password_hash=hash_password("pw"),
            first_name="No",
            last_name="Read",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(unauthorized)
        await db_session.flush()

        response = await client.get(
            f"/api/v1/designer/versions/{seeded['version'].id}/cycles",
            headers=auth(unauthorized),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"
