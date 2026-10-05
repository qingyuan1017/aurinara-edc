"""Unit tests for app.core.security module.

Tests cover JWT issue/verify, password hashing, reset tokens, MFA (TOTP),
re-authentication, inactivity handling, and Cognito token validation structure.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pyotp
import pytest

from app.core.security import (
    InvalidTokenError,
    check_inactivity,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    generate_mfa_secret,
    hash_password,
    validate_cognito_token,
    verify_mfa_code,
    verify_password,
    verify_re_auth,
    verify_reset_token,
)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    """Test bcrypt password hashing and verification."""

    def test_hash_password_returns_bcrypt_hash(self):
        hashed = hash_password("my-secret-password")
        assert hashed.startswith("$2b$")
        assert len(hashed) > 50

    def test_verify_password_correct(self):
        hashed = hash_password("correct-password")
        assert verify_password("correct-password", hashed) is True

    def test_verify_password_incorrect(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_produces_unique_values(self):
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        # bcrypt generates different salts each time
        assert h1 != h2

    def test_empty_password_can_be_hashed(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("not-empty", hashed) is False


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


class TestJWTTokens:
    """Test JWT creation and decoding."""

    def test_create_access_token_returns_string(self):
        token = create_access_token(uuid.uuid4())
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_roundtrip(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        payload = decode_token(token)

        assert payload.sub == str(user_id)
        assert payload.type == "access"
        assert payload.jti is not None
        assert payload.exp > datetime.now(UTC)

    def test_access_token_with_extra_claims(self):
        user_id = uuid.uuid4()
        extra = {"role": "admin", "study_id": "study-123"}
        token = create_access_token(user_id, extra_claims=extra)
        payload = decode_token(token)

        assert payload.extra == extra

    def test_access_token_custom_expiry(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, expires_delta=timedelta(minutes=5))
        payload = decode_token(token)

        # Token should expire in ~5 minutes
        expected_exp = datetime.now(UTC) + timedelta(minutes=5)
        assert abs((payload.exp - expected_exp).total_seconds()) < 5

    def test_create_refresh_token_returns_string(self):
        token = create_refresh_token(uuid.uuid4())
        assert isinstance(token, str)

    def test_refresh_token_roundtrip(self):
        user_id = uuid.uuid4()
        token = create_refresh_token(user_id)
        payload = decode_token(token)

        assert payload.sub == str(user_id)
        assert payload.type == "refresh"
        assert payload.jti is not None

    def test_refresh_token_longer_expiry(self):
        user_id = uuid.uuid4()
        access = create_access_token(user_id)
        refresh = create_refresh_token(user_id)

        access_payload = decode_token(access)
        refresh_payload = decode_token(refresh)

        # Refresh token should expire later than access token
        assert refresh_payload.exp > access_payload.exp

    def test_decode_expired_token_raises(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))

        with pytest.raises(InvalidTokenError, match="Token validation failed"):
            decode_token(token)

    def test_decode_tampered_token_raises(self):
        token = create_access_token(uuid.uuid4())
        # Tamper with the token by modifying a character
        tampered = token[:-5] + "XXXXX"

        with pytest.raises(InvalidTokenError):
            decode_token(tampered)

    def test_decode_garbage_token_raises(self):
        with pytest.raises(InvalidTokenError):
            decode_token("not-a-valid-jwt")

    def test_each_token_has_unique_jti(self):
        user_id = uuid.uuid4()
        t1 = create_access_token(user_id)
        t2 = create_access_token(user_id)
        p1 = decode_token(t1)
        p2 = decode_token(t2)
        assert p1.jti != p2.jti


# ---------------------------------------------------------------------------
# Reset tokens
# ---------------------------------------------------------------------------


class TestResetTokens:
    """Test password reset token generation and verification."""

    def test_create_reset_token_returns_tuple(self):
        token, expires_at = create_reset_token()
        assert isinstance(token, str)
        assert isinstance(expires_at, datetime)

    def test_reset_token_is_url_safe(self):
        token, _ = create_reset_token()
        # URL-safe base64 only uses alphanumeric, -, _
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_reset_token_not_expired_immediately(self):
        _, expires_at = create_reset_token()
        assert verify_reset_token(expires_at) is True

    def test_reset_token_expired(self):
        expired_at = datetime.now(UTC) - timedelta(minutes=1)
        assert verify_reset_token(expired_at) is False

    def test_each_reset_token_unique(self):
        t1, _ = create_reset_token()
        t2, _ = create_reset_token()
        assert t1 != t2

    def test_reset_token_expiry_in_future(self):
        _, expires_at = create_reset_token()
        assert expires_at > datetime.now(UTC)
        # Should be roughly 60 minutes from now
        delta = (expires_at - datetime.now(UTC)).total_seconds()
        assert 3500 < delta < 3700  # ~60 minutes


# ---------------------------------------------------------------------------
# MFA (TOTP)
# ---------------------------------------------------------------------------


class TestMFA:
    """Test MFA secret generation and TOTP code verification."""

    def test_generate_mfa_secret_returns_base32(self):
        secret = generate_mfa_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 16

    def test_verify_mfa_code_correct(self):
        secret = generate_mfa_secret()
        totp = pyotp.TOTP(secret)
        current_code = totp.now()

        assert verify_mfa_code(secret, current_code) is True

    def test_verify_mfa_code_incorrect(self):
        secret = generate_mfa_secret()
        assert verify_mfa_code(secret, "000000") is False

    def test_verify_mfa_code_allows_window(self):
        secret = generate_mfa_secret()
        totp = pyotp.TOTP(secret)
        # Generate code for previous time step (valid_window=1 should accept)
        previous_code = totp.at(datetime.now(UTC) - timedelta(seconds=30))
        assert verify_mfa_code(secret, previous_code) is True

    def test_each_secret_is_unique(self):
        s1 = generate_mfa_secret()
        s2 = generate_mfa_secret()
        assert s1 != s2


# ---------------------------------------------------------------------------
# Re-authentication
# ---------------------------------------------------------------------------


class TestReAuth:
    """Test re-authentication for sensitive operations."""

    def test_verify_re_auth_correct(self):
        password = "signature-password"
        hashed = hash_password(password)
        assert verify_re_auth(hashed, password) is True

    def test_verify_re_auth_incorrect(self):
        hashed = hash_password("correct-password")
        assert verify_re_auth(hashed, "wrong-password") is False


# ---------------------------------------------------------------------------
# Inactivity handling
# ---------------------------------------------------------------------------


class TestInactivity:
    """Test session inactivity timeout checking."""

    def test_none_last_activity_is_expired(self):
        assert check_inactivity(None) is True

    def test_recent_activity_not_expired(self):
        recent = datetime.now(UTC) - timedelta(minutes=5)
        assert check_inactivity(recent) is False

    def test_old_activity_is_expired(self):
        old = datetime.now(UTC) - timedelta(minutes=60)
        # Default timeout is 30 minutes
        assert check_inactivity(old) is True

    def test_custom_timeout(self):
        activity = datetime.now(UTC) - timedelta(minutes=10)
        # With 5-minute timeout, this should be expired
        assert check_inactivity(activity, timeout_minutes=5) is True
        # With 15-minute timeout, this should be active
        assert check_inactivity(activity, timeout_minutes=15) is False

    def test_exactly_at_boundary(self):
        # Activity exactly at the threshold boundary
        activity = datetime.now(UTC) - timedelta(minutes=30)
        # Should be expired (last_activity < threshold means expired)
        assert check_inactivity(activity, timeout_minutes=30) is True


# ---------------------------------------------------------------------------
# Cognito / OIDC token validation
# ---------------------------------------------------------------------------


class TestCognitoValidation:
    """Test Cognito/OIDC token validation."""

    def test_returns_none_when_not_configured(self):
        """When Cognito settings are absent, should return None without error."""
        result = validate_cognito_token("some-token")
        assert result is None

    @patch("app.core.security.get_settings")
    @patch("app.core.security._fetch_cognito_jwks")
    def test_raises_when_jwks_unavailable(self, mock_jwks, mock_settings):
        """When JWKS cannot be fetched, should raise InvalidTokenError."""
        mock_settings.return_value.cognito_user_pool_id = "us-east-1_abc123"
        mock_settings.return_value.cognito_region = "us-east-1"
        mock_settings.return_value.cognito_app_client_id = "client123"
        mock_jwks.return_value = None

        with pytest.raises(InvalidTokenError, match="Unable to fetch Cognito JWKS"):
            validate_cognito_token("some-token")

    @patch("app.core.security.get_settings")
    @patch("app.core.security._fetch_cognito_jwks")
    def test_raises_on_invalid_token(self, mock_jwks, mock_settings):
        """When token is invalid, should raise InvalidTokenError."""
        mock_settings.return_value.cognito_user_pool_id = "us-east-1_abc123"
        mock_settings.return_value.cognito_region = "us-east-1"
        mock_settings.return_value.cognito_app_client_id = "client123"
        mock_jwks.return_value = {"keys": []}

        with pytest.raises(InvalidTokenError):
            validate_cognito_token("invalid.jwt.token")

    @patch("app.core.security.jwt.decode")
    @patch(
        "app.core.security.jwt.get_unverified_header", return_value={"alg": "RS256", "kid": "key-1"}
    )
    @patch("app.core.security._fetch_cognito_jwks", return_value={"keys": [{"kid": "key-1"}]})
    @patch("app.core.security.get_settings")
    def test_access_token_uses_client_id_and_token_use(self, settings, jwks, header, decode):
        settings.return_value.cognito_user_pool_id = "us-east-1_pool"
        settings.return_value.cognito_region = "us-east-1"
        settings.return_value.cognito_app_client_id = "client123"
        decode.return_value = {
            "sub": "subject-1",
            "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_pool",
            "exp": datetime.now(UTC).timestamp() + 300,
            "token_use": "access",
            "client_id": "client123",
        }
        result = validate_cognito_token("token")
        assert result is not None
        assert result.token_use == "access"
        assert result.client_id == "client123"

    @patch("app.core.security.jwt.decode")
    @patch(
        "app.core.security.jwt.get_unverified_header", return_value={"alg": "RS256", "kid": "key-1"}
    )
    @patch("app.core.security._fetch_cognito_jwks", return_value={"keys": [{"kid": "key-1"}]})
    @patch("app.core.security.get_settings")
    def test_id_token_uses_audience(self, settings, jwks, header, decode):
        settings.return_value.cognito_user_pool_id = "pool"
        settings.return_value.cognito_region = "region"
        settings.return_value.cognito_app_client_id = "client"
        decode.return_value = {
            "sub": "subject-1",
            "iss": "https://cognito-idp.region.amazonaws.com/pool",
            "exp": datetime.now(UTC).timestamp() + 300,
            "token_use": "id",
            "aud": "client",
        }
        assert validate_cognito_token("token").token_use == "id"

    @pytest.mark.parametrize(
        "claims, message",
        [
            ({"token_use": "access", "client_id": "other"}, "client"),
            ({"token_use": "id", "aud": "other"}, "audience"),
            ({"token_use": "refresh", "client_id": "client"}, "Unsupported"),
        ],
    )
    @patch("app.core.security.jwt.decode")
    @patch(
        "app.core.security.jwt.get_unverified_header", return_value={"alg": "RS256", "kid": "key-1"}
    )
    @patch("app.core.security._fetch_cognito_jwks", return_value={"keys": [{"kid": "key-1"}]})
    @patch("app.core.security.get_settings")
    def test_rejects_wrong_cognito_claims(self, settings, jwks, header, decode, claims, message):
        settings.return_value.cognito_user_pool_id = "pool"
        settings.return_value.cognito_region = "region"
        settings.return_value.cognito_app_client_id = "client"
        decode.return_value = {
            "sub": "subject-1",
            "iss": "https://cognito-idp.region.amazonaws.com/pool",
            "exp": datetime.now(UTC).timestamp() + 300,
            **claims,
        }
        with pytest.raises(InvalidTokenError, match=message):
            validate_cognito_token("token")

    @patch("app.core.security.jwt.decode")
    @patch(
        "app.core.security.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "rotated-key"},
    )
    @patch(
        "app.core.security._fetch_cognito_jwks",
        side_effect=[{"keys": [{"kid": "old-key"}]}, {"keys": [{"kid": "rotated-key"}]}],
    )
    @patch("app.core.security.get_settings")
    def test_unknown_key_id_refreshes_jwks(self, settings, fetch_jwks, header, decode):
        settings.return_value.cognito_user_pool_id = "pool"
        settings.return_value.cognito_region = "region"
        settings.return_value.cognito_app_client_id = "client"
        decode.return_value = {
            "sub": "subject-1",
            "iss": "https://cognito-idp.region.amazonaws.com/pool",
            "exp": datetime.now(UTC).timestamp() + 300,
            "token_use": "access",
            "client_id": "client",
        }
        assert validate_cognito_token("token").sub == "subject-1"
        assert fetch_jwks.call_count == 2
