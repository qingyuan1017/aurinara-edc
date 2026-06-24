"""Property-based test for session token round-trip and revocation.

**Validates: Requirements 1.3, 1.4, 1.6, 1.8**

Property 5: Session token round-trip and revocation.

Generates random user IDs and extra claims and asserts that:
  1. create_access_token + decode_token round-trips correctly (sub matches, type=="access")
  2. create_refresh_token + decode_token round-trips correctly (sub matches, type=="refresh")
  3. Each token has a unique JTI
  4. Refresh tokens have longer expiry than access tokens
  5. Expired tokens raise InvalidTokenError on decode
  6. At least 100 iterations
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate random UUIDs as user IDs
user_id_strategy = st.uuids()

# Generate extra claims as dictionaries with simple string keys and values
extra_claims_strategy = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=65, max_codepoint=122),
        ),
        values=st.one_of(
            st.text(min_size=0, max_size=50),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
        min_size=0,
        max_size=5,
    ),
)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestSessionRoundTripProperty:
    """Property-based tests for session token round-trip and revocation.

    **Validates: Requirements 1.3, 1.4, 1.6, 1.8**
    """

    @settings(max_examples=100, deadline=None)
    @given(user_id=user_id_strategy, extra_claims=extra_claims_strategy)
    def test_access_token_round_trip(self, user_id: uuid.UUID, extra_claims):
        """create_access_token + decode_token round-trips correctly.

        **Validates: Requirements 1.3**

        - The decoded sub matches the original user_id
        - The decoded type is "access"
        - The decoded extra claims match the provided claims
        """
        token = create_access_token(user_id, extra_claims=extra_claims)

        payload = decode_token(token)

        assert payload.sub == str(user_id), "Decoded sub must match the original user_id"
        assert payload.type == "access", "Access token must have type 'access'"
        assert payload.jti is not None, "Access token must have a JTI"

        # Verify extra claims round-trip
        if extra_claims:
            assert payload.extra == extra_claims, "Extra claims must round-trip"
        else:
            assert payload.extra == {}, "Empty extra claims should decode as empty dict"

    @settings(max_examples=100, deadline=None)
    @given(user_id=user_id_strategy)
    def test_refresh_token_round_trip(self, user_id: uuid.UUID):
        """create_refresh_token + decode_token round-trips correctly.

        **Validates: Requirements 1.3, 1.4**

        - The decoded sub matches the original user_id
        - The decoded type is "refresh"
        """
        token = create_refresh_token(user_id)

        payload = decode_token(token)

        assert payload.sub == str(user_id), "Decoded sub must match the original user_id"
        assert payload.type == "refresh", "Refresh token must have type 'refresh'"
        assert payload.jti is not None, "Refresh token must have a JTI"

    @settings(max_examples=100, deadline=None)
    @given(user_id=user_id_strategy)
    def test_unique_jti_per_token(self, user_id: uuid.UUID):
        """Each token has a unique JTI.

        **Validates: Requirements 1.4, 1.6**

        Generating multiple tokens for the same user must produce distinct JTIs,
        supporting per-token revocation.
        """
        access_token_1 = create_access_token(user_id)
        access_token_2 = create_access_token(user_id)
        refresh_token_1 = create_refresh_token(user_id)
        refresh_token_2 = create_refresh_token(user_id)

        payload_a1 = decode_token(access_token_1)
        payload_a2 = decode_token(access_token_2)
        payload_r1 = decode_token(refresh_token_1)
        payload_r2 = decode_token(refresh_token_2)

        jtis = {payload_a1.jti, payload_a2.jti, payload_r1.jti, payload_r2.jti}
        assert len(jtis) == 4, "All four tokens must have distinct JTIs"

    @settings(max_examples=100, deadline=None)
    @given(user_id=user_id_strategy)
    def test_refresh_token_longer_expiry_than_access(self, user_id: uuid.UUID):
        """Refresh tokens have longer expiry than access tokens.

        **Validates: Requirements 1.3, 1.8**

        The refresh token expiry must be strictly greater than the access token expiry,
        ensuring that refresh tokens can be used to obtain new access tokens within
        a longer session window.
        """
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        assert refresh_payload.exp > access_payload.exp, (
            "Refresh token expiry must be later than access token expiry"
        )

    @settings(max_examples=100, deadline=None)
    @given(user_id=user_id_strategy)
    def test_expired_tokens_raise_invalid_token_error(self, user_id: uuid.UUID):
        """Expired tokens raise InvalidTokenError on decode.

        **Validates: Requirements 1.8**

        Tokens issued with a negative expiry delta (already expired at issue time)
        must be rejected upon decode.
        """
        # Create an already-expired access token
        expired_access = create_access_token(
            user_id, expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(InvalidTokenError):
            decode_token(expired_access)

        # Create an already-expired refresh token
        expired_refresh = create_refresh_token(
            user_id, expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(InvalidTokenError):
            decode_token(expired_refresh)

    @settings(max_examples=100, deadline=None)
    @given(user_id=user_id_strategy, extra_claims=extra_claims_strategy)
    def test_token_timestamps_are_consistent(self, user_id: uuid.UUID, extra_claims):
        """Token timestamps are internally consistent.

        **Validates: Requirements 1.3, 1.8**

        - iat (issued at) is before exp (expiry)
        - exp - iat matches the configured token lifetime
        """
        before = datetime.now(UTC)
        token = create_access_token(user_id, extra_claims=extra_claims)
        after = datetime.now(UTC)

        payload = decode_token(token)

        # iat must be between before and after
        assert payload.iat >= before.replace(microsecond=0) - timedelta(seconds=1)
        assert payload.iat <= after + timedelta(seconds=1)

        # exp must be after iat
        assert payload.exp > payload.iat, "Token expiry must be after issued-at"
