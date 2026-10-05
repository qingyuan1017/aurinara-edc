"""Auth_Service — authentication, session, password reset, and external token validation.

Satisfies Requirements:
  - 1.1: Issue signed access + refresh tokens on valid credentials.
  - 1.2: Reject invalid credentials without issuing tokens.
  - 1.3: Issue a new access token for a valid, unrevoked refresh token.
  - 1.4: Revoke the refresh token on logout.
  - 1.5: Return user identity + resolved Authorization_Scope.
  - 1.6: Single-use password reset token flow.
  - 1.7: Validate Cognito-issued tokens and map to internal user.
  - 1.8: Reject sessions idle beyond the configured inactivity window.
  - 1.9: Require valid MFA code before issuing tokens.
  - 3.5: Reject authentication for inactive users.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import (
    CognitoTokenPayload,
    InvalidTokenError,
    check_inactivity,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    exchange_cognito_code,
    hash_password,
    refresh_cognito_token,
    validate_cognito_token,
    verify_mfa_code,
    verify_password,
    verify_reset_token,
)
from app.models.identity import Role, RolePermission, User, UserRole, UserStatus
from app.models.revoked_token import RevokedToken
from app.schemas.auth import (
    CurrentUserResponse,
    RoleAssignment,
    TokenPair,
)

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails (invalid credentials, inactive user, etc.)."""

    pass


class AuthService:
    """Handles login, refresh, logout, current-user, password reset, and external tokens."""

    # ------------------------------------------------------------------
    # Login (Req 1.1, 1.2, 1.8, 1.9, 3.5)
    # ------------------------------------------------------------------

    async def login(
        self,
        session: AsyncSession,
        email: str,
        password: str,
        mfa_code: str | None = None,
    ) -> TokenPair:
        """Authenticate a user and issue a token pair.

        Steps:
          1. Look up user by email.
          2. Reject if user status is inactive (Req 3.5).
          3. Reject if credentials are invalid (Req 1.2).
          4. If MFA enabled, require valid mfa_code (Req 1.9).
          5. Check inactivity timeout (Req 1.8).
          6. Issue access + refresh token (Req 1.1).
          7. Update last_activity.

        Args:
            session: Active database session.
            email: User's email address.
            password: Plaintext password to verify.
            mfa_code: Optional TOTP code (required when MFA is enabled).

        Returns:
            A TokenPair with access and refresh tokens.

        Raises:
            AuthenticationError: If authentication fails for any reason.
        """
        # 1. Look up user
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if user is None:
            logger.warning("Login attempt for non-existent email: %s", email)
            raise AuthenticationError("Invalid credentials")

        # 2. Reject inactive users (Req 3.5)
        if user.status == UserStatus.inactive:
            logger.warning("Login attempt by inactive user: %s", user.id)
            raise AuthenticationError("Account is inactive")

        # 3. Verify password (Req 1.2)
        if user.password_hash is None or not verify_password(password, user.password_hash):
            logger.warning("Invalid password for user: %s", user.id)
            raise AuthenticationError("Invalid credentials")

        # 4. MFA check (Req 1.9)
        if user.mfa_enabled:
            if not mfa_code:
                raise AuthenticationError("MFA code required")
            if not user.mfa_secret:
                raise AuthenticationError("MFA is enabled but no secret configured")
            if not verify_mfa_code(user.mfa_secret, mfa_code):
                logger.warning("Invalid MFA code for user: %s", user.id)
                raise AuthenticationError("Invalid MFA code")

        # 5. Inactivity check (Req 1.8)
        # Only enforce inactivity if the user has a previous activity timestamp.
        # A first-time login (last_activity is None) is allowed.
        if user.last_activity is not None:
            # Ensure timezone-aware comparison (SQLite may return naive datetimes)
            last_act = user.last_activity
            if last_act.tzinfo is None:
                last_act = last_act.replace(tzinfo=UTC)
            if check_inactivity(last_act):
                logger.info(
                    "User %s passed inactivity check via re-authentication (login)",
                    user.id,
                )

        # 6. Issue tokens (Req 1.1)
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        # 7. Update last_activity
        user.last_activity = datetime.now(UTC)
        await session.flush()

        logger.info("Successful login for user: %s", user.id)
        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    # ------------------------------------------------------------------
    # Refresh (Req 1.3)
    # ------------------------------------------------------------------

    async def refresh(self, session: AsyncSession, refresh_token: str) -> str:
        """Issue a new access token from a valid, unrevoked refresh token.

        Args:
            session: Active database session.
            refresh_token: The encoded refresh JWT.

        Returns:
            A new access token string.

        Raises:
            InvalidTokenError: If the refresh token is invalid, expired, or revoked.
        """
        payload = decode_token(refresh_token)

        if payload.type != "refresh":
            raise InvalidTokenError("Token is not a refresh token")

        # Check revocation
        if payload.jti:
            revoked = await session.execute(
                select(RevokedToken).where(RevokedToken.jti == payload.jti)
            )
            if revoked.scalars().first() is not None:
                raise InvalidTokenError("Refresh token has been revoked")

        # Issue new access token
        return create_access_token(UUID(payload.sub))

    # ------------------------------------------------------------------
    # Logout (Req 1.4)
    # ------------------------------------------------------------------

    async def logout(self, session: AsyncSession, refresh_token: str) -> None:
        """Revoke a refresh token so it cannot be used again.

        Args:
            session: Active database session.
            refresh_token: The encoded refresh JWT to revoke.

        Raises:
            InvalidTokenError: If the token cannot be decoded.
        """
        payload = decode_token(refresh_token)

        if payload.type != "refresh":
            raise InvalidTokenError("Token is not a refresh token")

        if not payload.jti:
            raise InvalidTokenError("Token missing JTI claim")

        # Check if already revoked
        existing = await session.execute(
            select(RevokedToken).where(RevokedToken.jti == payload.jti)
        )
        if existing.scalars().first() is not None:
            return  # Already revoked, idempotent

        revoked = RevokedToken(
            jti=payload.jti,
            user_id=UUID(payload.sub),
            expires_at=payload.exp,
        )
        session.add(revoked)
        await session.flush()

        logger.info("Refresh token revoked for user: %s", payload.sub)

    # ------------------------------------------------------------------
    # Me — current user identity + scope (Req 1.5)
    # ------------------------------------------------------------------

    async def me(self, session: AsyncSession, user: User) -> CurrentUserResponse:
        """Return the current user's identity and resolved authorization scope.

        Args:
            session: Active database session.
            user: The authenticated User object.

        Returns:
            CurrentUserResponse with identity and role assignments.
        """
        # Eagerly load user_roles -> role -> role_permissions -> permission
        result = await session.execute(
            select(User)
            .where(User.id == user.id)
            .options(
                selectinload(User.user_roles)
                .selectinload(UserRole.role)
                .selectinload(Role.role_permissions)
                .selectinload(RolePermission.permission)
            )
        )
        loaded_user = result.scalars().first()
        if loaded_user is None:
            loaded_user = user

        roles: list[RoleAssignment] = []
        for ur in loaded_user.user_roles:
            role = ur.role
            permissions = [rp.permission.code for rp in role.role_permissions]
            roles.append(
                RoleAssignment(
                    role_name=role.name,
                    scope_level=role.scope_level,
                    study_id=ur.study_id,
                    site_id=ur.site_id,
                    permissions=permissions,
                )
            )

        return CurrentUserResponse(
            id=loaded_user.id,
            email=loaded_user.email,
            first_name=loaded_user.first_name,
            last_name=loaded_user.last_name,
            status=loaded_user.status,
            mfa_enabled=loaded_user.mfa_enabled,
            roles=roles,
        )

    # ------------------------------------------------------------------
    # Password reset (Req 1.6)
    # ------------------------------------------------------------------

    async def request_password_reset(self, session: AsyncSession, email: str) -> None:
        """Generate a reset token and store it on the user.

        If the email does not exist, returns silently to avoid user enumeration.

        Args:
            session: Active database session.
            email: The user's email address.
        """
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if user is None:
            # Silent return to prevent user enumeration
            logger.info("Password reset requested for non-existent email: %s", email)
            return

        token, expires_at = create_reset_token()

        user.reset_token = token
        user.reset_token_expires_at = expires_at
        await session.flush()

        logger.info("Password reset token generated for user: %s", user.id)

    async def reset_password(self, session: AsyncSession, token: str, new_password: str) -> None:
        """Verify a reset token and update the user's password.

        Args:
            session: Active database session.
            token: The reset token string.
            new_password: The new plaintext password.

        Raises:
            InvalidTokenError: If the token is invalid or expired.
        """
        result = await session.execute(select(User).where(User.reset_token == token))
        user = result.scalars().first()

        if user is None:
            raise InvalidTokenError("Invalid reset token")

        # Handle potential timezone-naive datetimes (e.g., from SQLite in tests)
        expires_at = user.reset_token_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if not verify_reset_token(expires_at):
            # Invalidate expired token
            user.reset_token = None
            user.reset_token_expires_at = None
            await session.flush()
            raise InvalidTokenError("Reset token has expired")

        # Update password and invalidate token (single-use)
        user.password_hash = hash_password(new_password)
        user.reset_token = None
        user.reset_token_expires_at = None
        await session.flush()

        logger.info("Password reset completed for user: %s", user.id)

    async def exchange_cognito_code(
        self, *, code: str, code_verifier: str, redirect_uri: str | None = None
    ) -> dict:
        return exchange_cognito_code(
            code=code, code_verifier=code_verifier, redirect_uri=redirect_uri
        )

    async def refresh_cognito(self, refresh_token: str) -> dict:
        return refresh_cognito_token(refresh_token)

    # ------------------------------------------------------------------
    # External token validation (Req 1.7)
    # ------------------------------------------------------------------

    async def validate_external_token(self, session: AsyncSession, token: str) -> User | None:
        """Validate a Cognito/OIDC token and map to an internal user.

        Args:
            session: Active database session.
            token: The raw JWT from the Authorization header.

        Returns:
            The mapped internal User, or None if Cognito is not configured.

        Raises:
            InvalidTokenError: If the token is invalid.
            AuthenticationError: If no internal user maps to the token subject.
        """
        payload: CognitoTokenPayload | None = validate_cognito_token(token)

        if payload is None:
            return None

        # Immutable provider subject is authoritative. Email is only a one-time
        # migration aid for a verified ID token and never a permanent key.
        result = await session.execute(
            select(User).where(
                User.external_identity_provider == "cognito",
                User.external_subject == payload.sub,
            )
        )
        user = result.scalars().first()
        if user is None and payload.token_use == "id" and payload.email and payload.email_verified:
            result = await session.execute(select(User).where(User.email == payload.email))
            candidate = result.scalars().first()
            if candidate is not None:
                if candidate.external_identity_provider or candidate.external_subject:
                    raise AuthenticationError("External identity is already mapped")
                candidate.external_identity_provider = "cognito"
                candidate.external_subject = payload.sub
                await session.flush()
                user = candidate

        if user is None:
            raise AuthenticationError(
                f"No internal user mapped to external identity: {payload.sub}"
            )

        if user.status == UserStatus.inactive:
            raise AuthenticationError("Account is inactive")

        return user


# Module-level singleton for convenience
auth_service = AuthService()
