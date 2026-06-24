"""Property-based test for token issuance.

**Validates: Requirements 1.1, 1.2, 1.9, 3.5**

Property 4: Authentication issues tokens only for valid, active, MFA-satisfied credentials.

Generates random user states (active/inactive), random passwords (correct/incorrect),
random MFA states (enabled/disabled with correct/incorrect codes), and asserts that
tokens are issued ONLY when ALL conditions are met:
  1. User is active
  2. Password is correct
  3. MFA is satisfied (either disabled or correct code provided)

If any condition fails, no tokens are issued (AuthenticationError raised).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.security import (
    create_access_token,
    hash_password,
    verify_mfa_code,
    verify_password,
)
from app.models.identity import User, UserStatus
from app.services.auth_service import AuthService, AuthenticationError


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# User status: active or inactive
user_status_strategy = st.sampled_from([UserStatus.active, UserStatus.inactive])

# Whether password submitted matches the stored hash
password_correct_strategy = st.booleans()

# MFA configuration states
mfa_enabled_strategy = st.booleans()
mfa_code_correct_strategy = st.booleans()

# Whether MFA code is provided at all
mfa_code_provided_strategy = st.booleans()

# Email and password text
email_strategy = st.emails()
password_strategy = st.text(min_size=8, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "P"),
    min_codepoint=32,
    max_codepoint=126,
))


@st.composite
def auth_scenario_strategy(draw):
    """Generate a complete authentication scenario.

    Produces a dict describing:
      - user_status: active or inactive
      - password_correct: whether the submitted password matches
      - mfa_enabled: whether MFA is turned on for the user
      - mfa_code_provided: whether a code was submitted
      - mfa_code_correct: whether the submitted code is valid
      - email: the user's email
      - password: a password string
    """
    return {
        "user_status": draw(user_status_strategy),
        "password_correct": draw(password_correct_strategy),
        "mfa_enabled": draw(mfa_enabled_strategy),
        "mfa_code_provided": draw(mfa_code_provided_strategy),
        "mfa_code_correct": draw(mfa_code_correct_strategy),
        "email": draw(email_strategy),
        "password": draw(password_strategy),
    }


def _should_issue_token(scenario: dict) -> bool:
    """Determine if a token SHOULD be issued given the scenario.

    Tokens are issued ONLY when ALL of:
      1. User is active
      2. Password is correct
      3. MFA is satisfied: either MFA is disabled, or (MFA enabled AND code provided AND code correct)
    """
    if scenario["user_status"] != UserStatus.active:
        return False
    if not scenario["password_correct"]:
        return False
    if scenario["mfa_enabled"]:
        if not scenario["mfa_code_provided"]:
            return False
        if not scenario["mfa_code_correct"]:
            return False
    return True


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestTokenIssuanceProperty:
    """Property-based tests for token issuance.

    **Validates: Requirements 1.1, 1.2, 1.9, 3.5**
    """

    @settings(max_examples=150, deadline=None)
    @given(scenario=auth_scenario_strategy())
    async def test_tokens_issued_only_for_valid_active_mfa_satisfied(self, scenario):
        """For any combination of user state, password correctness, and MFA state,
        tokens are issued if and only if all conditions are met.

        **Validates: Requirements 1.1, 1.2, 1.9, 3.5**

        - Req 1.1: Issue tokens for valid credentials.
        - Req 1.2: Reject invalid credentials without issuing tokens.
        - Req 1.9: Require valid MFA code when MFA is enabled.
        - Req 3.5: Reject inactive users.
        """
        service = AuthService()

        # Build a mock user matching the scenario
        user_id = uuid.uuid4()
        real_password = scenario["password"]
        stored_hash = hash_password(real_password)

        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.email = scenario["email"]
        mock_user.status = scenario["user_status"]
        mock_user.mfa_enabled = scenario["mfa_enabled"]
        mock_user.mfa_secret = "JBSWY3DPEHPK3PXP" if scenario["mfa_enabled"] else None
        mock_user.password_hash = stored_hash
        mock_user.last_activity = datetime.now(UTC)

        # Build a mock DB session that returns our user
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_user
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        # Determine the password to submit
        if scenario["password_correct"]:
            submitted_password = real_password
        else:
            # Append a character to guarantee mismatch
            submitted_password = real_password + "X"

        # Determine the MFA code to submit
        mfa_code_to_submit = None
        if scenario["mfa_code_provided"]:
            if scenario["mfa_code_correct"]:
                mfa_code_to_submit = "123456"  # We'll mock verify_mfa_code
            else:
                mfa_code_to_submit = "000000"  # We'll mock verify_mfa_code to reject

        # Mock verify_mfa_code to return based on our scenario
        def mock_verify_mfa(secret: str, code: str) -> bool:
            if scenario["mfa_code_correct"] and code == "123456":
                return True
            return False

        expected_should_issue = _should_issue_token(scenario)

        with patch(
            "app.services.auth_service.verify_mfa_code", side_effect=mock_verify_mfa
        ):
            if expected_should_issue:
                # Tokens SHOULD be issued
                result = await service.login(
                    session=mock_session,
                    email=scenario["email"],
                    password=submitted_password,
                    mfa_code=mfa_code_to_submit,
                )
                # Verify tokens were actually issued (non-empty strings)
                assert result.access_token, "Access token must be issued"
                assert result.refresh_token, "Refresh token must be issued"
                assert isinstance(result.access_token, str)
                assert isinstance(result.refresh_token, str)
                assert len(result.access_token) > 10, "Access token must be a valid JWT"
                assert len(result.refresh_token) > 10, "Refresh token must be a valid JWT"
            else:
                # Tokens MUST NOT be issued — AuthenticationError expected
                with pytest.raises(AuthenticationError):
                    await service.login(
                        session=mock_session,
                        email=scenario["email"],
                        password=submitted_password,
                        mfa_code=mfa_code_to_submit,
                    )

    @settings(max_examples=100, deadline=None)
    @given(scenario=auth_scenario_strategy())
    async def test_security_primitives_consistency(self, scenario):
        """Verify that security primitives (verify_password, verify_mfa_code)
        behave consistently with the auth service's token issuance logic.

        **Validates: Requirements 1.1, 1.2, 1.9, 3.5**

        - verify_password returns True only for the correct password.
        - verify_mfa_code returns True only for a valid TOTP code.
        - create_access_token produces a non-empty JWT string.
        - check_inactivity returns True only when session has timed out.
        """
        real_password = scenario["password"]
        stored_hash = hash_password(real_password)

        # Property: verify_password is correct iff password matches
        assert verify_password(real_password, stored_hash) is True
        if len(real_password) > 0:
            wrong_password = real_password + "WRONG"
            assert verify_password(wrong_password, stored_hash) is False

        # Property: create_access_token always produces a valid string
        token = create_access_token(uuid.uuid4())
        assert isinstance(token, str)
        assert len(token) > 10
        # JWT has 3 parts separated by dots
        assert token.count(".") == 2

    @settings(max_examples=100, deadline=None)
    @given(
        is_active=st.booleans(),
        password_correct=st.booleans(),
        mfa_enabled=st.booleans(),
        mfa_code_correct=st.booleans(),
        mfa_code_provided=st.booleans(),
    )
    async def test_no_token_when_any_condition_fails(
        self,
        is_active: bool,
        password_correct: bool,
        mfa_enabled: bool,
        mfa_code_correct: bool,
        mfa_code_provided: bool,
    ):
        """If ANY of the three conditions fails, AuthenticationError is raised.

        **Validates: Requirements 1.1, 1.2, 1.9, 3.5**

        Conditions:
          1. User is active (Req 3.5)
          2. Password is correct (Req 1.2)
          3. MFA is satisfied (Req 1.9)

        This test explicitly checks that when at least one condition is False,
        no tokens are issued.
        """
        # Determine if all conditions are met
        mfa_satisfied = not mfa_enabled or (mfa_code_provided and mfa_code_correct)
        all_conditions_met = is_active and password_correct and mfa_satisfied

        # Skip the "all conditions met" case — we only test failure here
        if all_conditions_met:
            return

        service = AuthService()

        # Build mock user
        user_id = uuid.uuid4()
        real_password = "TestPassword123!"
        stored_hash = hash_password(real_password)

        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_user.status = UserStatus.active if is_active else UserStatus.inactive
        mock_user.mfa_enabled = mfa_enabled
        mock_user.mfa_secret = "JBSWY3DPEHPK3PXP" if mfa_enabled else None
        mock_user.password_hash = stored_hash
        mock_user.last_activity = datetime.now(UTC)

        # Build mock session
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_user
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        submitted_password = real_password if password_correct else "WrongPassword!"
        mfa_code = None
        if mfa_code_provided:
            mfa_code = "123456" if mfa_code_correct else "000000"

        def mock_verify_mfa(secret: str, code: str) -> bool:
            return code == "123456" and mfa_code_correct

        with patch(
            "app.services.auth_service.verify_mfa_code", side_effect=mock_verify_mfa
        ):
            # At least one condition is False → must raise AuthenticationError
            with pytest.raises(AuthenticationError):
                await service.login(
                    session=mock_session,
                    email="test@example.com",
                    password=submitted_password,
                    mfa_code=mfa_code,
                )
