"""Unit tests for app.services.shared.auth_service.AuthService.

Tests cover login, refresh, logout, me, password reset, and external token validation.
Uses an in-memory SQLite database to test real DB interactions without external deps.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pyotp
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import (
    CognitoTokenPayload,
    InvalidTokenError,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.shared.revoked_token import RevokedToken
from app.services.shared.auth_service import AuthenticationError, AuthService


@pytest.mark.asyncio
async def test_enforced_platform_mode_rejects_jit_external_user(
    auth_service: AuthService, db_session: AsyncSession
) -> None:
    payload = CognitoTokenPayload(
        sub="unprojected-subject",
        email="unprojected@example.test",
        email_verified=True,
        token_use="id",
        iss="https://issuer.example",
        exp=datetime.now(UTC) + timedelta(minutes=5),
        audience="client",
    )
    with (
        patch("app.services.shared.auth_service.validate_oidc_token", return_value=None),
        patch("app.services.shared.auth_service.validate_cognito_token", return_value=payload),
        patch(
            "app.services.shared.auth_service.get_settings",
            return_value=SimpleNamespace(platform_authorization_mode="enforced"),
        ),
        pytest.raises(AuthenticationError),
    ):
        await auth_service.validate_external_token(db_session, "id-token")


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

    @patch("app.services.shared.auth_service.validate_cognito_token", return_value=None)
    async def test_returns_none_when_cognito_not_configured(
        self, _validate, auth_service, db_session
    ):
        result = await auth_service.validate_external_token(db_session, "any-token")
        assert result is None

    @patch("app.services.shared.auth_service.validate_cognito_token")
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

    @patch("app.services.shared.auth_service.validate_cognito_token")
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

    @patch("app.services.shared.auth_service.validate_cognito_token")
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

    async def test_cognito_access_token_falls_back_after_generic_oidc_audience_failure(
        self, auth_service, db_session, active_user
    ):
        active_user.external_identity_provider = "oidc"
        active_user.external_issuer = "https://issuer"
        active_user.external_subject = "cognito-subject"
        await db_session.flush()

        payload = CognitoTokenPayload(
            sub="cognito-subject",
            token_use="access",
            iss="https://issuer",
            exp=datetime.now(UTC) + timedelta(minutes=5),
            client_id="client",
        )
        with (
            patch(
                "app.services.shared.auth_service.validate_oidc_token",
                side_effect=InvalidTokenError("OIDC token validation failed"),
            ),
            patch(
                "app.services.shared.auth_service.validate_cognito_token",
                return_value=payload,
            ) as validate_cognito,
        ):
            mapped = await auth_service.validate_external_token(db_session, "access-token")

        assert mapped is active_user
        validate_cognito.assert_called_once_with("access-token")

    async def test_generic_oidc_failure_is_preserved_when_cognito_is_not_configured(
        self, auth_service, db_session
    ):
        with (
            patch(
                "app.services.shared.auth_service.validate_oidc_token",
                side_effect=InvalidTokenError("OIDC token validation failed"),
            ),
            patch(
                "app.services.shared.auth_service.validate_cognito_token",
                return_value=None,
            ),
            pytest.raises(InvalidTokenError, match="OIDC token validation failed"),
        ):
            await auth_service.validate_external_token(db_session, "invalid-token")


# ---------------------------------------------------------------------------
# JIT provisioning tests
# ---------------------------------------------------------------------------


def _id_token_payload(
    *,
    sub: str = "new-cognito-subject",
    email: str = "newuser@example.com",
    email_verified: bool = True,
    given_name: str | None = None,
    family_name: str | None = None,
    name: str | None = None,
) -> CognitoTokenPayload:
    """Build a verified ID-token payload for provisioning tests."""
    return CognitoTokenPayload(
        sub=sub,
        email=email,
        email_verified=email_verified,
        token_use="id",
        iss="https://issuer",
        exp=datetime.now(UTC) + timedelta(minutes=5),
        audience="client",
        given_name=given_name,
        family_name=family_name,
        name=name,
    )


async def _count(db_session: AsyncSession, model) -> int:
    """Return the number of rows for the given model."""
    result = await db_session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


class TestJitProvisioning:
    """Test AuthService.validate_external_token JIT provisioning of new users."""

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_verified_id_token_provisions_active_roleless_user(
        self, validate, auth_service, db_session
    ):
        validate.return_value = _id_token_payload(given_name="Grace", family_name="Hopper")
        user = await auth_service.validate_external_token(db_session, "id-token")

        assert user is not None
        assert user.external_identity_provider == "cognito"
        assert user.external_subject == "new-cognito-subject"
        assert user.email == "newuser@example.com"
        assert user.status == UserStatus.active
        assert user.password_hash is None
        # Zero roles is the deliberate security default.
        assert await _count(db_session, UserRole) == 0

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_provisioned_user_has_names_from_given_family_claims(
        self, validate, auth_service, db_session
    ):
        validate.return_value = _id_token_payload(given_name="Grace", family_name="Hopper")
        user = await auth_service.validate_external_token(db_session, "id-token")
        assert user.first_name == "Grace"
        assert user.last_name == "Hopper"

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_names_fall_back_to_split_name_claim(self, validate, auth_service, db_session):
        validate.return_value = _id_token_payload(name="Jane Q Doe")
        user = await auth_service.validate_external_token(db_session, "id-token")
        assert user.first_name == "Jane"
        assert user.last_name == "Q Doe"

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_names_fall_back_to_email_local_part(self, validate, auth_service, db_session):
        validate.return_value = _id_token_payload(email="johnny@example.com")
        user = await auth_service.validate_external_token(db_session, "id-token")
        assert user.first_name == "johnny"
        assert user.last_name == "johnny"

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_partial_name_claims_combine_sources(self, validate, auth_service, db_session):
        # given_name present, family_name missing -> last_name from email local-part.
        validate.return_value = _id_token_payload(email="smith@example.com", given_name="Ada")
        user = await auth_service.validate_external_token(db_session, "id-token")
        assert user.first_name == "Ada"
        assert user.last_name == "smith"

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_access_token_unknown_subject_does_not_provision(
        self, validate, auth_service, db_session
    ):
        validate.return_value = CognitoTokenPayload(
            sub="access-only-subject",
            email="noone@example.com",
            email_verified=True,
            token_use="access",
            iss="https://issuer",
            exp=datetime.now(UTC) + timedelta(minutes=5),
            client_id="client",
        )
        before = await _count(db_session, User)
        with pytest.raises(AuthenticationError, match="No internal user mapped"):
            await auth_service.validate_external_token(db_session, "access-token")
        assert await _count(db_session, User) == before

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_unverified_id_token_does_not_provision(self, validate, auth_service, db_session):
        validate.return_value = _id_token_payload(email_verified=False)
        before = await _count(db_session, User)
        with pytest.raises(AuthenticationError, match="No internal user mapped"):
            await auth_service.validate_external_token(db_session, "id-token")
        assert await _count(db_session, User) == before

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_id_token_without_email_does_not_provision(
        self, validate, auth_service, db_session
    ):
        payload = _id_token_payload()
        payload.email = None
        validate.return_value = payload
        before = await _count(db_session, User)
        with pytest.raises(AuthenticationError, match="No internal user mapped"):
            await auth_service.validate_external_token(db_session, "id-token")
        assert await _count(db_session, User) == before

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_provisioning_is_idempotent(self, validate, auth_service, db_session):
        validate.return_value = _id_token_payload(given_name="Grace", family_name="Hopper")
        first = await auth_service.validate_external_token(db_session, "id-token")
        second = await auth_service.validate_external_token(db_session, "id-token")
        assert first.id == second.id
        assert await _count(db_session, User) == 1

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_provisioning_writes_sanitized_audit_event(
        self, validate, auth_service, db_session
    ):
        validate.return_value = _id_token_payload(given_name="Grace", family_name="Hopper")
        user = await auth_service.validate_external_token(db_session, "id-token")

        result = await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "provision_external")
        )
        events = result.scalars().all()
        assert len(events) == 1
        event = events[0]
        assert event.entity_id == user.id
        assert event.entity_type == "user"
        assert event.actor_id is None
        assert event.actor_kind == "external"
        assert "new-cognito-subject" in event.new_value
        assert "id-token" not in event.new_value

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_inactive_provisioned_user_not_reactivated(
        self, validate, auth_service, db_session, inactive_user
    ):
        # An existing inactive user already linked by subject is still rejected;
        # JIT never touches an existing row.
        inactive_user.external_identity_provider = "cognito"
        inactive_user.external_subject = "inactive-id-subject"
        await db_session.flush()
        validate.return_value = _id_token_payload(
            sub="inactive-id-subject", email=inactive_user.email
        )
        with pytest.raises(AuthenticationError, match="Account is inactive"):
            await auth_service.validate_external_token(db_session, "id-token")

    @patch("app.services.shared.auth_service.validate_cognito_token")
    async def test_existing_subject_match_still_works(
        self, validate, auth_service, db_session, active_user
    ):
        active_user.external_identity_provider = "cognito"
        active_user.external_subject = "existing-subject"
        await db_session.flush()
        before = await _count(db_session, User)
        validate.return_value = _id_token_payload(sub="existing-subject", email=active_user.email)
        mapped = await auth_service.validate_external_token(db_session, "id-token")
        assert mapped.id == active_user.id
        # No provisioning occurred.
        assert await _count(db_session, User) == before
