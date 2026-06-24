"""Security primitives for the Clinical EDC system.

Provides JWT issue/verify, password hashing, reset tokens, MFA (TOTP),
re-authentication, inactivity handling, and optional Cognito/OIDC token validation.

Satisfies Requirements:
  - 1.1: Issue signed access + refresh tokens on valid credentials.
  - 1.2: Reject invalid credentials without issuing tokens.
  - 1.7: Validate Cognito-issued JWTs and map token subject to internal User.
  - 1.8: Reject sessions idle beyond the configured inactivity window.
  - 1.9: Require a valid MFA code before issuing tokens.
  - 3.5: Reject authentication for inactive Users.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Password hashing (bcrypt via passlib)
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt.

    Returns the hashed string suitable for storage.
    """
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Returns True if the password matches, False otherwise.
    """
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT token management (Requirement 1.1)
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"


class TokenPayload(BaseModel):
    """Decoded JWT payload."""

    sub: str  # user ID as string
    exp: datetime
    iat: datetime
    type: str  # "access" or "refresh"
    jti: str | None = None
    extra: dict[str, Any] = {}


def create_access_token(
    user_id: UUID | str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed access token for the given user.

    Args:
        user_id: The internal user identifier.
        extra_claims: Additional claims to embed in the token payload.
        expires_delta: Custom expiry duration; defaults to settings value.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": now + expires_delta,
        "iat": now,
        "type": "access",
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload["extra"] = extra_claims

    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def create_refresh_token(
    user_id: UUID | str,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed refresh token for the given user.

    Args:
        user_id: The internal user identifier.
        expires_delta: Custom expiry duration; defaults to settings value.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": now + expires_delta,
        "iat": now,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
    }

    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a locally issued JWT.

    Args:
        token: The encoded JWT string.

    Returns:
        Parsed TokenPayload with validated claims.

    Raises:
        InvalidTokenError: If the token is expired, malformed, or invalid.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError(f"Token validation failed: {exc}") from exc

    return TokenPayload(
        sub=payload["sub"],
        exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
        iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
        type=payload.get("type", "access"),
        jti=payload.get("jti"),
        extra=payload.get("extra", {}),
    )


# ---------------------------------------------------------------------------
# Reset tokens — single-use, time-limited (Requirement 1.6)
# ---------------------------------------------------------------------------

_RESET_TOKEN_EXPIRY_MINUTES = 60


def create_reset_token() -> tuple[str, datetime]:
    """Generate a cryptographically secure, single-use password reset token.

    Returns:
        A tuple of (token_string, expiry_datetime).
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=_RESET_TOKEN_EXPIRY_MINUTES)
    return token, expires_at


def verify_reset_token(token_expires_at: datetime) -> bool:
    """Check whether a reset token is still within its validity window.

    Args:
        token_expires_at: The stored expiry timestamp of the reset token.

    Returns:
        True if the token is still valid (not expired), False otherwise.
    """
    return datetime.now(UTC) < token_expires_at


# ---------------------------------------------------------------------------
# MFA — TOTP via pyotp (Requirement 1.9)
# ---------------------------------------------------------------------------


def generate_mfa_secret() -> str:
    """Generate a new TOTP secret for MFA enrollment.

    Returns:
        A base32-encoded secret string suitable for QR code generation.
    """
    return pyotp.random_base32()


def verify_mfa_code(secret: str, code: str) -> bool:
    """Verify a TOTP code against a user's MFA secret.

    Allows a ±1 window to accommodate minor clock drift.

    Args:
        secret: The user's base32-encoded TOTP secret.
        code: The 6-digit code submitted by the user.

    Returns:
        True if the code is valid within the allowed window, False otherwise.
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# ---------------------------------------------------------------------------
# Re-authentication (Requirement 17.1)
# ---------------------------------------------------------------------------


def verify_re_auth(password_hash: str, password: str) -> bool:
    """Re-authenticate a user before sensitive operations (e.g., signatures).

    This is a simple wrapper around password verification used specifically
    in the re-authentication context (e.g., before electronic signatures).

    Args:
        password_hash: The stored bcrypt hash for the user.
        password: The plaintext password submitted for re-authentication.

    Returns:
        True if credentials are valid, False otherwise.
    """
    return verify_password(password, password_hash)


# ---------------------------------------------------------------------------
# Inactivity handling (Requirement 1.8)
# ---------------------------------------------------------------------------


def check_inactivity(last_activity: datetime | None, timeout_minutes: int | None = None) -> bool:
    """Determine whether a session has exceeded the inactivity timeout.

    Args:
        last_activity: The timestamp of the user's last recorded activity.
            If None, the session is considered expired.
        timeout_minutes: Override for the inactivity window; defaults to settings value.

    Returns:
        True if the session has expired due to inactivity, False if still active.
    """
    if last_activity is None:
        return True

    settings = get_settings()
    timeout = timeout_minutes if timeout_minutes is not None else settings.inactivity_timeout_minutes
    threshold = datetime.now(UTC) - timedelta(minutes=timeout)
    return last_activity < threshold


# ---------------------------------------------------------------------------
# Optional Cognito / OIDC token validation (Requirement 1.7)
# ---------------------------------------------------------------------------


class CognitoTokenPayload(BaseModel):
    """Claims extracted from a validated Cognito/OIDC JWT."""

    sub: str  # Cognito user pool subject (UUID)
    email: str | None = None
    token_use: str | None = None  # "access" or "id"
    iss: str | None = None
    exp: datetime | None = None


# In-memory JWKS cache (populated on first call when Cognito is configured)
_jwks_cache: dict[str, Any] | None = None


def _get_cognito_jwks_url() -> str | None:
    """Build the Cognito JWKS URI from settings. Returns None if not configured."""
    settings = get_settings()
    if not settings.cognito_user_pool_id or not settings.cognito_region:
        return None
    return (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
    )


def _fetch_cognito_jwks() -> dict[str, Any] | None:
    """Fetch JWKS from Cognito. Returns None if not configured or fetch fails.

    Uses a simple in-memory cache to avoid repeated network calls.
    In production, this would use async HTTP with TTL-based refresh.
    """
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache

    url = _get_cognito_jwks_url()
    if url is None:
        return None

    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=5) as resp:
            import json

            _jwks_cache = json.loads(resp.read())
            return _jwks_cache
    except Exception:
        return None


def validate_cognito_token(token: str) -> CognitoTokenPayload | None:
    """Validate a Cognito-issued JWT against the configured JWKS.

    If Cognito is not configured (pool ID / region not set), returns None immediately.
    On successful validation, returns the decoded claims. On failure, raises
    InvalidTokenError.

    Args:
        token: The raw JWT string from the Authorization header.

    Returns:
        CognitoTokenPayload with decoded claims, or None if Cognito is not configured.

    Raises:
        InvalidTokenError: If the token is invalid, expired, or from an untrusted issuer.
    """
    settings = get_settings()
    if not settings.cognito_user_pool_id or not settings.cognito_region:
        return None

    expected_issuer = (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}"
    )

    jwks = _fetch_cognito_jwks()
    if jwks is None:
        raise InvalidTokenError("Unable to fetch Cognito JWKS for token validation")

    try:
        # Decode the token header to find the key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise InvalidTokenError("Token header missing 'kid'")

        # Find the matching key in JWKS
        rsa_key: dict[str, Any] = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if not rsa_key:
            raise InvalidTokenError("Token key ID not found in Cognito JWKS")

        # Verify and decode
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.cognito_app_client_id,
            issuer=expected_issuer,
        )

        return CognitoTokenPayload(
            sub=payload["sub"],
            email=payload.get("email"),
            token_use=payload.get("token_use"),
            iss=payload.get("iss"),
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC) if "exp" in payload else None,
        )

    except JWTError as exc:
        raise InvalidTokenError(f"Cognito token validation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTokenError(Exception):
    """Raised when a token is invalid, expired, or cannot be verified."""

    pass


class InactiveUserError(Exception):
    """Raised when an inactive user attempts to authenticate (Requirement 3.5)."""

    pass
