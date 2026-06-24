"""Integration tests for auth routes and get_current_user dependency.

Tests cover:
  - POST /auth/login (Requirement 1.1, 1.2)
  - POST /auth/refresh (Requirement 1.3)
  - POST /auth/logout (Requirement 1.4)
  - GET /auth/me (Requirement 1.5)
  - POST /auth/forgot-password (Requirement 1.6)
  - POST /auth/reset-password (Requirement 1.6)
  - get_current_user dependency (Requirements 1.1, 1.7, 21.1)

Uses an in-memory SQLite database and HTTPX async client against the app.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.main import create_app
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    """Create an async SQLite engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    """Yield an async session for testing."""
    session_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
async def active_user(db_session: AsyncSession) -> User:
    """Create and persist an active user with a known password."""
    user = User(
        id=uuid.uuid4(),
        email="testuser@example.com",
        password_hash=hash_password("valid-password"),
        first_name="Test",
        last_name="User",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def user_with_role(db_session: AsyncSession) -> User:
    """Create a user with an assigned role and permissions."""
    perm = Permission(id=uuid.uuid4(), code="subject.read", description="Read subjects")
    db_session.add(perm)
    await db_session.flush()

    role = Role(
        id=uuid.uuid4(),
        name="Investigator",
        scope_level="site",
        is_system=True,
    )
    db_session.add(role)
    await db_session.flush()

    rp = RolePermission(role_id=role.id, permission_id=perm.id)
    db_session.add(rp)
    await db_session.flush()

    user = User(
        id=uuid.uuid4(),
        email="investigator@example.com",
        password_hash=hash_password("inv-password"),
        first_name="Inv",
        last_name="Estigator",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()

    study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    ur = UserRole(user_id=user.id, role_id=role.id, study_id=study_id, site_id=site_id)
    db_session.add(ur)
    await db_session.flush()

    return user


@pytest.fixture
def app(async_engine):
    """Create a fresh app instance with the test DB session override."""
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
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Login route tests
# ---------------------------------------------------------------------------


class TestLoginRoute:
    """Test POST /api/v1/auth/login."""

    async def test_login_success(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com", "password": "valid-password"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_invalid_credentials(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "anything"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Refresh route tests
# ---------------------------------------------------------------------------


class TestRefreshRoute:
    """Test POST /api/v1/auth/refresh."""

    async def test_refresh_success(self, client, active_user):
        refresh_token = create_refresh_token(active_user.id)
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_refresh_invalid_token(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "garbage-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout route tests
# ---------------------------------------------------------------------------


class TestLogoutRoute:
    """Test POST /api/v1/auth/logout."""

    async def test_logout_success(self, client, active_user):
        refresh_token = create_refresh_token(active_user.id)
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 204

    async def test_logout_invalid_token(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "garbage-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Me route tests
# ---------------------------------------------------------------------------


class TestMeRoute:
    """Test GET /api/v1/auth/me."""

    async def test_me_success(self, client, active_user):
        token = create_access_token(active_user.id)
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(active_user.id)
        assert data["email"] == "testuser@example.com"
        assert data["first_name"] == "Test"
        assert data["last_name"] == "User"
        assert data["status"] == "active"

    async def test_me_no_auth_header(self, client, active_user):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_invalid_token(self, client, active_user):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-garbage"},
        )
        assert resp.status_code == 401

    async def test_me_with_roles(self, client, user_with_role):
        token = create_access_token(user_with_role.id)
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["roles"]) == 1
        assert data["roles"][0]["role_name"] == "Investigator"
        assert "subject.read" in data["roles"][0]["permissions"]


# ---------------------------------------------------------------------------
# Forgot password route tests
# ---------------------------------------------------------------------------


class TestForgotPasswordRoute:
    """Test POST /api/v1/auth/forgot-password."""

    async def test_forgot_password_existing_email(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "testuser@example.com"},
        )
        assert resp.status_code == 202
        assert "reset link" in resp.json()["message"].lower()

    async def test_forgot_password_unknown_email(self, client, active_user):
        # Should still return 202 to prevent user enumeration
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "unknown@example.com"},
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Reset password route tests
# ---------------------------------------------------------------------------


class TestResetPasswordRoute:
    """Test POST /api/v1/auth/reset-password."""

    async def test_reset_password_invalid_token(self, client, active_user):
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "nonexistent", "new_password": "newpass123"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user dependency tests
# ---------------------------------------------------------------------------


class TestGetCurrentUserDependency:
    """Test the get_current_user dependency via /auth/me."""

    async def test_rejects_refresh_token_as_access(self, client, active_user):
        """A refresh token should not be accepted as an access token."""
        refresh_token = create_refresh_token(active_user.id)
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert resp.status_code == 401
