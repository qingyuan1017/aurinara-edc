"""Unit tests for app.services.auth_service.AuthService.

Tests cover login, refresh, logout, me, password reset, and external token validation.
Uses an in-memory SQLite database to test real DB interactions without external deps.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pyotp
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import (
    CognitoTokenPayload,
    InvalidTokenError,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.revoked_token import RevokedToken
from app.services.auth_service import AuthenticationError, AuthService

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
def auth_service():
    """Return a fresh AuthService instance."""
    return AuthService()


@pytest.fixture
async def active_user(db_session: AsyncSession) -> User:
    """Create and persist an active user with a known password."""
    user = User(
        id=uuid.uuid4(),
        email="alice@example.com",
        password_hash=hash_password("correct-password"),
        first_name="Alice",
        last_name="Smith",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """Create and persist an inactive user."""
    user = User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        password_hash=hash_password("password123"),
        first_name="Bob",
        last_name="Inactive",
        status=UserStatus.inactive,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def mfa_user(db_session: AsyncSession) -> User:
    """Create and persist a user with MFA enabled."""
    secret = pyotp.random_base32()
    user = User(
        id=uuid.uuid4(),
        email="mfa@example.com",
        password_hash=hash_password("mfa-password"),
        first_name="Carol",
        last_name="MFA",
        status=UserStatus.active,
        mfa_enabled=True,
        mfa_secret=secret,
        last_activity=datetime.now(UTC) - timedelta(minutes=2),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def user_with_role(db_session: AsyncSession) -> User:
    """Create a user with an assigned role and permissions."""
    # Create permission
    perm = Permission(id=uuid.uuid4(), code="form.enter", description="Enter form data")
    db_session.add(perm)
    await db_session.flush()

    # Create role
    role = Role(
        id=uuid.uuid4(),
        name="Site Coordinator",
        scope_level="site",
        is_system=True,
    )
    db_session.add(role)
    await db_session.flush()

    # Link permission to role
    rp = RolePermission(role_id=role.id, permission_id=perm.id)
    db_session.add(rp)
    await db_session.flush()

    # Create user
    user = User(
        id=uuid.uuid4(),
        email="coordinated@example.com",
        password_hash=hash_password("pass123"),
        first_name="Dan",
        last_name="Coordinator",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()

    # Assign role
    study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    ur = UserRole(
        user_id=user.id,
        role_id=role.id,
        study_id=study_id,
        site_id=site_id,
    )
    db_session.add(ur)
    await db_session.flush()

    return user


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


class TestLogin:
    """Test AuthService.login."""

    async def test_successful_login(self, auth_service, db_session, active_user):
        result = await auth_service.login(db_session, "alice@example.com", "correct-password")
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

    async def test_login_updates_last_activity(self, auth_service, db_session, active_user):
        before = active_user.last_activity
        await auth_service.login(db_session, "alice@example.com", "correct-password")
        assert active_user.last_activity > before

    async def test_login_nonexistent_email_raises(self, auth_service, db_session, active_user):
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.login(db_session, "nobody@example.com", "anything")

    async def test_login_wrong_password_raises(self, auth_service, db_session, active_user):
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.login(db_session, "alice@example.com", "wrong-password")

    async def test_login_inactive_user_raises(self, auth_service, db_session, inactive_user):
        with pytest.raises(AuthenticationError, match="Account is inactive"):
            await auth_service.login(db_session, "inactive@example.com", "password123")

    async def test_login_mfa_required_but_not_provided(self, auth_service, db_session, mfa_user):
        with pytest.raises(AuthenticationError, match="MFA code required"):
            await auth_service.login(db_session, "mfa@example.com", "mfa-password")

    async def test_login_mfa_invalid_code(self, auth_service, db_session, mfa_user):
        with pytest.raises(AuthenticationError, match="Invalid MFA code"):
            await auth_service.login(
                db_session, "mfa@example.com", "mfa-password", mfa_code="000000"
            )

    async def test_login_mfa_valid_code(self, auth_service, db_session, mfa_user):
        totp = pyotp.TOTP(mfa_user.mfa_secret)
        valid_code = totp.now()
        result = await auth_service.login(
            db_session, "mfa@example.com", "mfa-password", mfa_code=valid_code
        )
        assert result.access_token
        assert result.refresh_token

    async def test_login_tokens_decode_correctly(self, auth_service, db_session, active_user):
        result = await auth_service.login(db_session, "alice@example.com", "correct-password")
        access_payload = decode_token(result.access_token)
        refresh_payload = decode_token(result.refresh_token)

        assert access_payload.sub == str(active_user.id)
        assert access_payload.type == "access"
        assert refresh_payload.sub == str(active_user.id)
        assert refresh_payload.type == "refresh"


# ---------------------------------------------------------------------------
# Refresh tests
# ---------------------------------------------------------------------------


class TestRefresh:
    """Test AuthService.refresh."""

    async def test_refresh_issues_new_access_token(self, auth_service, db_session, active_user):
        refresh = create_refresh_token(active_user.id)
        new_access = await auth_service.refresh(db_session, refresh)
        assert isinstance(new_access, str)

        payload = decode_token(new_access)
        assert payload.sub == str(active_user.id)
        assert payload.type == "access"

    async def test_refresh_rejects_access_token(self, auth_service, db_session, active_user):
        from app.core.security import create_access_token

        access = create_access_token(active_user.id)
        with pytest.raises(InvalidTokenError, match="not a refresh token"):
            await auth_service.refresh(db_session, access)

    async def test_refresh_rejects_revoked_token(self, auth_service, db_session, active_user):
        refresh = create_refresh_token(active_user.id)
        # Revoke it first
        await auth_service.logout(db_session, refresh)
        # Now try to refresh
        with pytest.raises(InvalidTokenError, match="revoked"):
            await auth_service.refresh(db_session, refresh)

    async def test_refresh_rejects_invalid_token(self, auth_service, db_session):
        with pytest.raises(InvalidTokenError):
            await auth_service.refresh(db_session, "garbage-token")


# ---------------------------------------------------------------------------
# Logout tests
# ---------------------------------------------------------------------------


class TestLogout:
    """Test AuthService.logout."""

    async def test_logout_revokes_token(self, auth_service, db_session, active_user):
        refresh = create_refresh_token(active_user.id)
        await auth_service.logout(db_session, refresh)

        # Verify token is stored in revoked_tokens
        payload = decode_token(refresh)
        result = await db_session.execute(
            RevokedToken.__table__.select().where(RevokedToken.jti == payload.jti)
        )
        row = result.first()
        assert row is not None

    async def test_logout_idempotent(self, auth_service, db_session, active_user):
        refresh = create_refresh_token(active_user.id)
        await auth_service.logout(db_session, refresh)
        # Second call should not raise
        await auth_service.logout(db_session, refresh)

    async def test_logout_rejects_access_token(self, auth_service, db_session, active_user):
        from app.core.security import create_access_token

        access = create_access_token(active_user.id)
        with pytest.raises(InvalidTokenError, match="not a refresh token"):
            await auth_service.logout(db_session, access)


# ---------------------------------------------------------------------------
# Me tests
# ---------------------------------------------------------------------------


class TestMe:
    """Test AuthService.me."""

    async def test_me_returns_identity(self, auth_service, db_session, active_user):
        result = await auth_service.me(db_session, active_user)
        assert result.id == active_user.id
        assert result.email == "alice@example.com"
        assert result.first_name == "Alice"
        assert result.last_name == "Smith"
        assert result.status == "active"
        assert result.mfa_enabled is False

    async def test_me_returns_roles(self, auth_service, db_session, user_with_role):
        result = await auth_service.me(db_session, user_with_role)
        assert result.id == user_with_role.id
        assert len(result.roles) == 1
        role = result.roles[0]
        assert role.role_name == "Site Coordinator"
        assert role.scope_level == "site"
        assert "form.enter" in role.permissions


# ---------------------------------------------------------------------------
# Password reset tests
# ---------------------------------------------------------------------------


class TestPasswordReset:
    """Test AuthService.request_password_reset and reset_password."""

    async def test_request_reset_stores_token(self, auth_service, db_session, active_user):
        await auth_service.request_password_reset(db_session, "alice@example.com")
        await db_session.refresh(active_user)
        assert active_user.reset_token is not None
        assert active_user.reset_token_expires_at is not None
        # Compare without timezone since SQLite stores naive datetimes
        expires_at = active_user.reset_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        assert expires_at > datetime.now(UTC)

    async def test_request_reset_silent_for_unknown_email(self, auth_service, db_session):
        # Should not raise
        await auth_service.request_password_reset(db_session, "unknown@example.com")

    async def test_reset_password_updates_hash(self, auth_service, db_session, active_user):
        await auth_service.request_password_reset(db_session, "alice@example.com")
        await db_session.refresh(active_user)
        token = active_user.reset_token

        await auth_service.reset_password(db_session, token, "new-secure-password")
        await db_session.refresh(active_user)

        # Old password should no longer work
        with pytest.raises(AuthenticationError):
            await auth_service.login(db_session, "alice@example.com", "correct-password")

        # New password should work
        result = await auth_service.login(db_session, "alice@example.com", "new-secure-password")
        assert result.access_token

    async def test_reset_password_invalidates_token(self, auth_service, db_session, active_user):
        await auth_service.request_password_reset(db_session, "alice@example.com")
        await db_session.refresh(active_user)
        token = active_user.reset_token

        await auth_service.reset_password(db_session, token, "new-password")
        await db_session.refresh(active_user)

        # Token should be cleared (single-use)
        assert active_user.reset_token is None
        assert active_user.reset_token_expires_at is None

    async def test_reset_password_rejects_invalid_token(self, auth_service, db_session):
        with pytest.raises(InvalidTokenError, match="Invalid reset token"):
            await auth_service.reset_password(db_session, "nonexistent-token", "anything")

    async def test_reset_password_rejects_expired_token(
        self, auth_service, db_session, active_user
    ):
        # Manually set an expired token
        active_user.reset_token = "expired-token-value"
        active_user.reset_token_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db_session.flush()

        with pytest.raises(InvalidTokenError, match="expired"):
            await auth_service.reset_password(db_session, "expired-token-value", "new-pass")


# ---------------------------------------------------------------------------
# External token validation tests
# ---------------------------------------------------------------------------


class TestValidateExternalToken:
    """Test AuthService.validate_external_token."""

    async def test_returns_none_when_cognito_not_configured(self, auth_service, db_session):
        # Default settings have no Cognito configured
        result = await auth_service.validate_external_token(db_session, "any-token")
        assert result is None

    @patch("app.services.auth_service.validate_cognito_token")
    async def test_external_subject_mapping_does_not_use_email(
        self, validate, auth_service, db_session, active_user
    ):
        validate.return_value = CognitoTokenPayload(
            sub="cognito-subject",
            email=active_user.email,
            token_use="access",
            iss="https://issuer",
            exp=datetime.now(UTC) + timedelta(minutes=5),
            client_id="client",
        )
        with pytest.raises(AuthenticationError, match="No internal user mapped"):
            await auth_service.validate_external_token(db_session, "access-token")

    @patch("app.services.auth_service.validate_cognito_token")
    async def test_verified_id_token_links_legacy_user_once(
        self, validate, auth_service, db_session, active_user
    ):
        validate.return_value = CognitoTokenPayload(
            sub="cognito-subject",
            email=active_user.email,
            token_use="id",
            iss="https://issuer",
            exp=datetime.now(UTC) + timedelta(minutes=5),
            audience="client",
            email_verified=True,
        )
        mapped = await auth_service.validate_external_token(db_session, "id-token")
        assert mapped is active_user
        assert active_user.external_identity_provider == "cognito"
        assert active_user.external_subject == "cognito-subject"

    @patch("app.services.auth_service.validate_cognito_token")
    async def test_external_mapping_rejects_inactive_user(
        self, validate, auth_service, db_session, inactive_user
    ):
        inactive_user.external_identity_provider = "cognito"
        inactive_user.external_subject = "inactive-subject"
        await db_session.flush()
        validate.return_value = CognitoTokenPayload(
            sub="inactive-subject",
            token_use="access",
            iss="https://issuer",
            exp=datetime.now(UTC) + timedelta(minutes=5),
            client_id="client",
        )
        with pytest.raises(AuthenticationError, match="Account is inactive"):
            await auth_service.validate_external_token(db_session, "access-token")
