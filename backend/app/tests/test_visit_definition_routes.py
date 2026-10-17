"""Focused route tests for the Designer visit-definition endpoints (FEAT-001).

Covers the version-scoped POST/GET visit-definition surface mounted under
``/api/v1/designer/versions/{version_id}/visits``: draft creation, inverted
window rejection, the published-version immutability guard, ordered listing,
and server-side default-deny authorization.
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
from app.models.designer.visit import VisitDefinition
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
        code="designer.visit.read",
        description="Read visit definitions",
    )
    configure_permission = Permission(
        id=uuid.uuid4(),
        code="designer.visit.configure",
        description="Configure visit definitions",
    )
    role = Role(id=uuid.uuid4(), name="Designer_Role", scope_level="system", is_system=True)
    user = User(
        id=uuid.uuid4(),
        email="visits@example.test",
        password_hash=hash_password("pw"),
        first_name="Visit",
        last_name="Designer",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([read_permission, configure_permission, role, user])
    await db_session.flush()
    db_session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=read_permission.id),
            RolePermission(role_id=role.id, permission_id=configure_permission.id),
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )

    study = Study(
        id=uuid.uuid4(),
        study_code="VD-001",
        title="Visit Definition Study",
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
    published_version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="2.0",
        status=StudyVersionStatus.published,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([study, version, published_version])
    await db_session.flush()
    return {
        "user": user,
        "study": study,
        "version": version,
        "published_version": published_version,
    }


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


VISIT_BODY = {
    "name": "Screening",
    "visit_number": 1,
    "visit_type": "scheduled",
    "target_day": 0,
    "window_before": 3,
    "window_after": 3,
    "display_order": 1,
    "is_required": True,
    "addable": True,
}


class TestVisitDefinitionRoutes:
    async def test_post_creates_visit_on_draft_version(self, client, seeded):
        response = await client.post(
            f"/api/v1/designer/versions/{seeded['version'].id}/visits",
            json=VISIT_BODY,
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["name"] == VISIT_BODY["name"]
        assert payload["visit_number"] == VISIT_BODY["visit_number"]
        assert payload["visit_type"] == VISIT_BODY["visit_type"]
        assert payload["target_day"] == VISIT_BODY["target_day"]
        assert payload["window_before"] == VISIT_BODY["window_before"]
        assert payload["window_after"] == VISIT_BODY["window_after"]
        assert payload["display_order"] == VISIT_BODY["display_order"]
        assert payload["is_required"] == VISIT_BODY["is_required"]
        assert payload["addable"] is True
        assert payload["study_version_id"] == str(seeded["version"].id)

    async def test_post_inverted_window_rejected_and_persists_nothing(
        self, client, seeded, db_session
    ):
        # A genuinely inverted window: the service treats window_before as the
        # lower-edge offset (lower_edge = -window_before) and window_after as the
        # upper edge, so -window_before > window_after only holds when a bound is
        # negative. Negative offsets are the only inverted window reachable over
        # the HTTP surface; the schema's ge=0 bound rejects them with a 422
        # ValidationError before anything is persisted (Requirement 4.3).
        inverted = {
            **VISIT_BODY,
            "window_before": -1,
            "window_after": -2,
        }
        response = await client.post(
            f"/api/v1/designer/versions/{seeded['version'].id}/visits",
            json=inverted,
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ValidationError"
        remaining = (await db_session.execute(select(VisitDefinition))).scalars().all()
        assert remaining == []

    async def test_post_on_published_version_rejected_by_guard(self, client, seeded):
        response = await client.post(
            f"/api/v1/designer/versions/{seeded['published_version'].id}/visits",
            json=VISIT_BODY,
            headers=auth(seeded["user"]),
        )
        assert response.status_code != 201
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BusinessRuleError"

    async def test_get_returns_definitions_ordered_by_display_order(
        self, client, seeded, db_session
    ):
        later = VisitDefinition(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Follow-up",
            visit_number=2,
            visit_type="scheduled",
            target_day=28,
            window_before=3,
            window_after=3,
            display_order=2,
            is_required=True,
            created_at=datetime.now(UTC),
        )
        earlier = VisitDefinition(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Baseline",
            visit_number=1,
            visit_type="scheduled",
            target_day=0,
            window_before=1,
            window_after=1,
            display_order=1,
            is_required=True,
            created_at=datetime.now(UTC),
        )
        db_session.add_all([later, earlier])
        await db_session.flush()

        response = await client.get(
            f"/api/v1/designer/versions/{seeded['version'].id}/visits",
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == ["Baseline", "Follow-up"]

    async def test_post_default_deny_without_configure_permission(self, client, db_session, seeded):
        unauthorized = User(
            id=uuid.uuid4(),
            email="no-configure@example.test",
            password_hash=hash_password("pw"),
            first_name="No",
            last_name="Configure",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(unauthorized)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/designer/versions/{seeded['version'].id}/visits",
            json=VISIT_BODY,
            headers=auth(unauthorized),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"

    async def test_get_default_deny_without_read_permission(self, client, db_session, seeded):
        unauthorized = User(
            id=uuid.uuid4(),
            email="no-read@example.test",
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
            f"/api/v1/designer/versions/{seeded['version'].id}/visits",
            headers=auth(unauthorized),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"
