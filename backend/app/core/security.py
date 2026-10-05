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

import json
import secrets
import time
import urllib.parse
import urllib.request
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
        return TokenPayload(
            sub=payload["sub"],
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
            iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
            type=payload.get("type", "access"),
            jti=payload.get("jti"),
            extra=payload.get("extra", {}),
        )
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError("Token validation failed") from exc


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
    timeout = (
        timeout_minutes if timeout_minutes is not None else settings.inactivity_timeout_minutes
    )
    threshold = datetime.now(UTC) - timedelta(minutes=timeout)
    return last_activity < threshold


# ---------------------------------------------------------------------------
# Optional Cognito / OIDC token validation (Requirement 1.7)
# ---------------------------------------------------------------------------


class CognitoTokenPayload(BaseModel):
    """Claims extracted from a validated Cognito JWT."""

    sub: str
    email: str | None = None
    email_verified: bool = False
    token_use: str
    iss: str
    exp: datetime
    client_id: str | None = None
    audience: str | list[str] | None = None


# Bounded process-local cache. A key miss forces one refresh for Cognito rotation.
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expires_at = 0.0


def _get_cognito_jwks_url() -> str | None:
    """Build the Cognito JWKS URI from settings. Returns None if not configured."""
    settings = get_settings()
    if not settings.cognito_user_pool_id or not settings.cognito_region:
        return None
    return (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
    )


def _fetch_cognito_jwks(*, force_refresh: bool = False) -> dict[str, Any] | None:
    global _jwks_cache, _jwks_cache_expires_at
    now = time.monotonic()
    if not force_refresh and _jwks_cache is not None and now < _jwks_cache_expires_at:
        return _jwks_cache
    url = _get_cognito_jwks_url()
    if url is None:
        return None
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            result = json.loads(resp.read())
        if not isinstance(result, dict) or not isinstance(result.get("keys"), list):
            return None
        _jwks_cache = result
        _jwks_cache_expires_at = now + max(60, int(get_settings().cognito_jwks_cache_ttl_seconds))
        return result
    except Exception:
        return None


def validate_cognito_token(token: str) -> CognitoTokenPayload | None:
    """Validate Cognito signature and token-use-specific claims."""
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
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise InvalidTokenError("Unsupported Cognito token algorithm")
        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("Token header missing 'kid'")
        rsa_key = next((key for key in jwks.get("keys", []) if key.get("kid") == kid), None)
        if rsa_key is None:
            refreshed = _fetch_cognito_jwks(force_refresh=True)
            if refreshed is None:
                raise InvalidTokenError("Unable to refresh Cognito JWKS")
            rsa_key = next(
                (key for key in refreshed.get("keys", []) if key.get("kid") == kid), None
            )
        if rsa_key is None:
            raise InvalidTokenError("Token key ID not found in Cognito JWKS")
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=expected_issuer,
            options={"verify_aud": False},
        )
        token_use = payload.get("token_use")
        if token_use not in {"access", "id"}:
            raise InvalidTokenError("Unsupported Cognito token type")
        if not isinstance(payload.get("sub"), str) or not payload["sub"]:
            raise InvalidTokenError("Cognito token has an invalid subject")
        if not isinstance(payload.get("exp"), (int, float)):
            raise InvalidTokenError("Cognito token has an invalid expiry")
        client_id = settings.cognito_app_client_id
        if not client_id:
            raise InvalidTokenError("Cognito app client is not configured")
        audience = payload.get("aud")
        if token_use == "access" and payload.get("client_id") != client_id:
            raise InvalidTokenError("Cognito access token client is not trusted")
        if (
            token_use == "id"
            and audience != client_id
            and not (isinstance(audience, list) and client_id in audience)
        ):
            raise InvalidTokenError("Cognito ID token audience is not trusted")
        return CognitoTokenPayload(
            sub=payload["sub"],
            email=payload.get("email"),
            email_verified=payload.get("email_verified") is True,
            token_use=token_use,
            iss=payload["iss"],
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
            client_id=payload.get("client_id"),
            audience=audience,
        )
    except InvalidTokenError:
        raise
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError("Cognito token validation failed") from exc


def _cognito_token_endpoint() -> str | None:
    domain = get_settings().cognito_domain
    if not domain:
        return None
    domain = domain.rstrip("/")
    if domain.startswith("http://"):
        domain = "https://" + domain[len("http://") :]
    elif not domain.startswith("https://"):
        domain = f"https://{domain}"
    return f"{domain}/oauth2/token"


def _post_cognito_token(values: dict[str, str]) -> dict[str, Any]:
    settings = get_settings()
    endpoint = _cognito_token_endpoint()
    if endpoint is None or not settings.cognito_app_client_id:
        raise InvalidTokenError("Cognito OAuth is not configured")
    request = urllib.request.Request(
        endpoint,
        data=urllib.parse.urlencode(values).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read())
    except Exception as exc:
        raise InvalidTokenError("Cognito OAuth request failed") from exc
    if not isinstance(result, dict) or not isinstance(result.get("access_token"), str):
        raise InvalidTokenError("Cognito OAuth response is invalid")
    return result


def exchange_cognito_code(
    *, code: str, code_verifier: str, redirect_uri: str | None = None
) -> dict[str, Any]:
    """Exchange a short-lived authorization code using public-client PKCE."""
    settings = get_settings()
    configured_redirect = settings.cognito_redirect_uri
    effective_redirect = redirect_uri or configured_redirect
    if (
        not code
        or not code_verifier
        or not configured_redirect
        or effective_redirect != configured_redirect
    ):
        raise InvalidTokenError("Cognito redirect URI is not allowed")
    return _post_cognito_token(
        {
            "grant_type": "authorization_code",
            "client_id": settings.cognito_app_client_id or "",
            "code": code,
            "redirect_uri": effective_redirect,
            "code_verifier": code_verifier,
        }
    )


def refresh_cognito_token(refresh_token: str) -> dict[str, Any]:
    """Refresh Cognito tokens through Cognito's token endpoint."""
    if not refresh_token:
        raise InvalidTokenError("Cognito refresh token is missing")
    settings = get_settings()
    return _post_cognito_token(
        {
            "grant_type": "refresh_token",
            "client_id": settings.cognito_app_client_id or "",
            "refresh_token": refresh_token,
        }
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTokenError(Exception):
    """Raised when a token is invalid, expired, or cannot be verified."""

    pass


class InactiveUserError(Exception):
    """Raised when an inactive user attempts to authenticate (Requirement 3.5)."""

    pass
