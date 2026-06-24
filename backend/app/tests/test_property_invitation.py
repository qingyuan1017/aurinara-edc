"""Property-based test for the invitation lifecycle round-trip.

**Validates: Requirements 3.1, 3.2**

Property 6: Invitation lifecycle round-trip.

Generates random invitation data (emails, role_ids, study/site scopes) and asserts:
  1. An invitation created with invite() has status=pending and a valid token.
  2. Accepting with the correct token produces an active user with the invitation's role at scope.
  3. Accepting with an invalid/expired token raises InvitationError.
  4. Double-accepting raises InvitationError.
  5. At least 100 iterations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.request_context import request_id_var
from app.models.identity import (
    Invitation,
    InvitationStatus,
    Role,
    User,
    UserRole,
    UserStatus,
)
from app.schemas.user import InvitationCreate
from app.services.user_service import InvitationError, UserService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate random email-like strings that satisfy EmailStr validation
email_strategy = st.from_regex(
    r"[a-z][a-z0-9]{2,10}@[a-z]{3,8}\.(com|org|net|io)",
    fullmatch=True,
)

# Generate random UUIDs for role_id, study_id, site_id
uuid_strategy = st.uuids()

# Optional study/site scope (None or a UUID)
optional_uuid_strategy = st.one_of(st.none(), st.uuids())

# Simple password strings for accept_invitation
password_strategy = st.text(
    min_size=8,
    max_size=30,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        min_codepoint=33,
        max_codepoint=126,
    ),
)

# Simple name strings
name_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L",), min_codepoint=65, max_codepoint=122),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_engine_and_session():
    """Create in-memory SQLite async engine and session for a single test run."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, session_factory


async def _setup_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    """Create a role with the given ID for the test."""
    role = Role(
        id=role_id,
        name=f"TestRole-{role_id.hex[:8]}",
        scope_level="site",
        is_system=False,
    )
    session.add(role)
    await session.flush()
    return role


async def _setup_admin(session: AsyncSession) -> User:
    """Create an admin user to act as the inviter."""
    from app.core.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email="admin-inviter@test.local",
        password_hash=hash_password("admin-pass"),
        first_name="Admin",
        last_name="Inviter",
        status=UserStatus.active,
    )
    session.add(user)
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestInvitationLifecycleProperty:
    """Property-based tests for invitation lifecycle round-trip.

    **Validates: Requirements 3.1, 3.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        email=email_strategy,
        role_id=uuid_strategy,
        study_id=optional_uuid_strategy,
        site_id=optional_uuid_strategy,
    )
    @pytest.mark.asyncio
    async def test_invite_creates_pending_invitation_with_valid_token(
        self,
        email: str,
        role_id: uuid.UUID,
        study_id: uuid.UUID | None,
        site_id: uuid.UUID | None,
    ):
        """invite() creates an invitation with status=pending and a non-empty token.

        **Validates: Requirements 3.1**

        For any valid email, role_id, and scope combination:
        - The returned invitation has status == pending.
        - The token is a non-empty string.
        - The invitation email matches the input.
        - The invitation role_id matches the input.
        - The invitation study_id and site_id match the input.
        - The expires_at is in the future.
        """
        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    # Setup: create role and admin
                    await _setup_role(session, role_id)
                    admin = await _setup_admin(session)

                    # Act
                    svc = UserService()
                    data = InvitationCreate(
                        email=email,
                        role_id=role_id,
                        study_id=study_id,
                        site_id=site_id,
                    )
                    invitation = await svc.invite(session, data, admin.id)

                    # Assert
                    assert invitation.status == InvitationStatus.pending
                    assert invitation.token is not None
                    assert len(invitation.token) > 0
                    assert invitation.email == email
                    assert invitation.role_id == role_id
                    assert invitation.study_id == study_id
                    assert invitation.site_id == site_id
                    assert invitation.expires_at > datetime.now(UTC)
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)

    @settings(max_examples=100, deadline=None)
    @given(
        email=email_strategy,
        role_id=uuid_strategy,
        study_id=optional_uuid_strategy,
        site_id=optional_uuid_strategy,
        password=password_strategy,
        first_name=name_strategy,
        last_name=name_strategy,
    )
    @pytest.mark.asyncio
    async def test_accept_with_correct_token_activates_user_with_role_at_scope(
        self,
        email: str,
        role_id: uuid.UUID,
        study_id: uuid.UUID | None,
        site_id: uuid.UUID | None,
        password: str,
        first_name: str,
        last_name: str,
    ):
        """Accepting with the correct token produces an active user with the invitation's role.

        **Validates: Requirements 3.1, 3.2**

        For any valid invitation data:
        - After accept_invitation, the user has status == active.
        - The user has a UserRole with the invitation's role_id, study_id, site_id.
        """
        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    # Setup
                    await _setup_role(session, role_id)
                    admin = await _setup_admin(session)

                    # Create invitation
                    svc = UserService()
                    data = InvitationCreate(
                        email=email,
                        role_id=role_id,
                        study_id=study_id,
                        site_id=site_id,
                    )
                    invitation = await svc.invite(session, data, admin.id)

                    # Accept
                    user = await svc.accept_invitation(
                        session,
                        token=invitation.token,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                    )

                    # Assert user is active
                    assert user.status == UserStatus.active
                    assert user.email == email
                    assert user.first_name == first_name
                    assert user.last_name == last_name

                    # Assert role assignment at scope
                    from sqlalchemy import select

                    result = await session.execute(
                        select(UserRole).where(UserRole.user_id == user.id)
                    )
                    user_roles = result.scalars().all()
                    assert len(user_roles) == 1
                    assert user_roles[0].role_id == role_id
                    assert user_roles[0].study_id == study_id
                    assert user_roles[0].site_id == site_id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)

    @settings(max_examples=100, deadline=None)
    @given(
        email=email_strategy,
        role_id=uuid_strategy,
        invalid_token=st.text(min_size=10, max_size=50, alphabet=st.characters(min_codepoint=48, max_codepoint=122)),
    )
    @pytest.mark.asyncio
    async def test_accept_with_invalid_token_raises_invitation_error(
        self,
        email: str,
        role_id: uuid.UUID,
        invalid_token: str,
    ):
        """Accepting with an invalid token raises InvitationError.

        **Validates: Requirements 3.2**

        For any token not matching a real invitation, accept_invitation must raise.
        """
        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    # Setup: create role and admin, create a real invitation
                    await _setup_role(session, role_id)
                    admin = await _setup_admin(session)

                    svc = UserService()
                    data = InvitationCreate(
                        email=email,
                        role_id=role_id,
                    )
                    invitation = await svc.invite(session, data, admin.id)

                    # Try to accept with invalid token (guaranteed different from real token)
                    bad_token = invalid_token + "_INVALID"

                    with pytest.raises(InvitationError):
                        await svc.accept_invitation(
                            session,
                            token=bad_token,
                            password="test-pass-123",
                            first_name="X",
                            last_name="Y",
                        )
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)

    @settings(max_examples=100, deadline=None)
    @given(
        email=email_strategy,
        role_id=uuid_strategy,
    )
    @pytest.mark.asyncio
    async def test_accept_expired_invitation_raises_invitation_error(
        self,
        email: str,
        role_id: uuid.UUID,
    ):
        """Accepting an expired invitation raises InvitationError.

        **Validates: Requirements 3.2**

        If an invitation's expires_at is in the past, accept_invitation must raise.
        """
        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    # Setup
                    await _setup_role(session, role_id)
                    admin = await _setup_admin(session)

                    # Create invitation normally then expire it
                    svc = UserService()
                    data = InvitationCreate(
                        email=email,
                        role_id=role_id,
                    )
                    invitation = await svc.invite(session, data, admin.id)

                    # Manually set expires_at to the past
                    invitation.expires_at = datetime.now(UTC) - timedelta(hours=1)
                    await session.flush()

                    # Try to accept — should fail because expired
                    with pytest.raises(InvitationError):
                        await svc.accept_invitation(
                            session,
                            token=invitation.token,
                            password="test-pass-123",
                            first_name="X",
                            last_name="Y",
                        )
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)

    @settings(max_examples=100, deadline=None)
    @given(
        email=email_strategy,
        role_id=uuid_strategy,
        password=password_strategy,
        first_name=name_strategy,
        last_name=name_strategy,
    )
    @pytest.mark.asyncio
    async def test_double_accept_raises_invitation_error(
        self,
        email: str,
        role_id: uuid.UUID,
        password: str,
        first_name: str,
        last_name: str,
    ):
        """Double-accepting the same invitation raises InvitationError.

        **Validates: Requirements 3.1, 3.2**

        Once an invitation has been accepted, any subsequent attempt to accept
        the same token must raise InvitationError.
        """
        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    # Setup
                    await _setup_role(session, role_id)
                    admin = await _setup_admin(session)

                    # Create and accept invitation
                    svc = UserService()
                    data = InvitationCreate(
                        email=email,
                        role_id=role_id,
                    )
                    invitation = await svc.invite(session, data, admin.id)

                    # First accept — should succeed
                    await svc.accept_invitation(
                        session,
                        token=invitation.token,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                    )

                    # Second accept — should raise
                    with pytest.raises(InvitationError):
                        await svc.accept_invitation(
                            session,
                            token=invitation.token,
                            password="other-pass-456",
                            first_name="Other",
                            last_name="Person",
                        )
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)
