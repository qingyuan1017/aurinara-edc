"""Unit tests for app.services.user_service.UserService.

Tests cover invite, accept_invitation, deactivate, and assign_roles.
Uses an in-memory SQLite database to test real DB interactions without external deps.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.request_context import request_id_var
from app.core.security import hash_password, verify_password
from app.models.identity import (
    Invitation,
    InvitationStatus,
    Role,
    User,
    UserRole,
    UserStatus,
)
from app.schemas.user import InvitationCreate, RoleAssignmentRequest
from app.services.user_service import InvitationError, UserService

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
    """Yield an async session for testing with request context set."""
    session_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    # Set a request_id in context so audit_service.record() can populate the field
    token = request_id_var.set(str(uuid.uuid4()))
    async with session_factory() as session:
        yield session
    request_id_var.reset(token)


@pytest.fixture
def user_service():
    """Return a fresh UserService instance."""
    return UserService()


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create and persist an admin user for use as actor."""
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash=hash_password("admin-pass"),
        first_name="Admin",
        last_name="User",
        status=UserStatus.active,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def site_coordinator_role(db_session: AsyncSession) -> Role:
    """Create and persist a site coordinator role."""
    role = Role(
        id=uuid.uuid4(),
        name="Site Coordinator",
        scope_level="site",
        is_system=True,
    )
    db_session.add(role)
    await db_session.flush()
    return role


@pytest.fixture
async def data_manager_role(db_session: AsyncSession) -> Role:
    """Create and persist a data manager role."""
    role = Role(
        id=uuid.uuid4(),
        name="Data Manager",
        scope_level="study",
        is_system=True,
    )
    db_session.add(role)
    await db_session.flush()
    return role


@pytest.fixture
async def pending_invitation(
    db_session: AsyncSession, admin_user: User, site_coordinator_role: Role
) -> Invitation:
    """Create a valid pending invitation."""
    study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    invitation = Invitation(
        id=uuid.uuid4(),
        email="newuser@example.com",
        token="valid-token-abc123",
        role_id=site_coordinator_role.id,
        study_id=study_id,
        site_id=site_id,
        invited_by=admin_user.id,
        status=InvitationStatus.pending,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=72),
    )
    db_session.add(invitation)
    await db_session.flush()
    return invitation


@pytest.fixture
async def expired_invitation(
    db_session: AsyncSession, admin_user: User, site_coordinator_role: Role
) -> Invitation:
    """Create an expired invitation."""
    invitation = Invitation(
        id=uuid.uuid4(),
        email="expired@example.com",
        token="expired-token-xyz",
        role_id=site_coordinator_role.id,
        study_id=None,
        site_id=None,
        invited_by=admin_user.id,
        status=InvitationStatus.pending,
        created_at=datetime.now(UTC) - timedelta(hours=100),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(invitation)
    await db_session.flush()
    return invitation


@pytest.fixture
async def active_user(db_session: AsyncSession) -> User:
    """Create an active user for deactivation tests."""
    user = User(
        id=uuid.uuid4(),
        email="active@example.com",
        password_hash=hash_password("password123"),
        first_name="Active",
        last_name="Person",
        status=UserStatus.active,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Invite tests
# ---------------------------------------------------------------------------


class TestInvite:
    """Test UserService.invite."""

    async def test_invite_creates_invitation(
        self, user_service, db_session, admin_user, site_coordinator_role
    ):
        data = InvitationCreate(
            email="invited@example.com",
            role_id=site_coordinator_role.id,
            study_id=uuid.uuid4(),
            site_id=uuid.uuid4(),
        )
        invitation = await user_service.invite(db_session, data, admin_user.id)

        assert invitation.email == "invited@example.com"
        assert invitation.role_id == site_coordinator_role.id
        assert invitation.status == InvitationStatus.pending
        assert invitation.token is not None
        assert invitation.invited_by == admin_user.id
        assert invitation.expires_at > datetime.now(UTC)

    async def test_invite_writes_audit_event(
        self, user_service, db_session, admin_user, site_coordinator_role
    ):
        from app.models.audit import AuditEvent

        data = InvitationCreate(
            email="audited@example.com",
            role_id=site_coordinator_role.id,
        )
        invitation = await user_service.invite(db_session, data, admin_user.id)

        # Verify audit event was written
        result = await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "invitation",
                AuditEvent.entity_id == invitation.id,
                AuditEvent.action == "invite",
            )
        )
        audit_event = result.scalar_one_or_none()
        assert audit_event is not None
        assert audit_event.actor_id == admin_user.id
        assert audit_event.new_value == "audited@example.com"


# ---------------------------------------------------------------------------
# Accept invitation tests
# ---------------------------------------------------------------------------


class TestAcceptInvitation:
    """Test UserService.accept_invitation."""

    async def test_accept_creates_and_activates_user(
        self, user_service, db_session, pending_invitation
    ):
        user = await user_service.accept_invitation(
            db_session,
            token="valid-token-abc123",
            password="secure-pass-123",
            first_name="New",
            last_name="User",
        )

        assert user.email == "newuser@example.com"
        assert user.status == UserStatus.active
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert verify_password("secure-pass-123", user.password_hash)

    async def test_accept_assigns_role_at_scope(
        self, user_service, db_session, pending_invitation, site_coordinator_role
    ):
        user = await user_service.accept_invitation(
            db_session,
            token="valid-token-abc123",
            password="secure-pass-123",
            first_name="New",
            last_name="User",
        )

        # Verify role assignment
        result = await db_session.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        )
        user_roles = result.scalars().all()
        assert len(user_roles) == 1
        assert user_roles[0].role_id == site_coordinator_role.id
        assert user_roles[0].study_id == pending_invitation.study_id
        assert user_roles[0].site_id == pending_invitation.site_id

    async def test_accept_marks_invitation_accepted(
        self, user_service, db_session, pending_invitation
    ):
        await user_service.accept_invitation(
            db_session,
            token="valid-token-abc123",
            password="secure-pass-123",
            first_name="New",
            last_name="User",
        )

        await db_session.refresh(pending_invitation)
        assert pending_invitation.status == InvitationStatus.accepted
        assert pending_invitation.accepted_at is not None

    async def test_accept_writes_audit_event(
        self, user_service, db_session, pending_invitation
    ):
        from app.models.audit import AuditEvent

        user = await user_service.accept_invitation(
            db_session,
            token="valid-token-abc123",
            password="secure-pass-123",
            first_name="New",
            last_name="User",
        )

        result = await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "user",
                AuditEvent.entity_id == user.id,
                AuditEvent.action == "accept_invitation",
            )
        )
        audit_event = result.scalar_one_or_none()
        assert audit_event is not None

    async def test_accept_rejects_invalid_token(self, user_service, db_session):
        with pytest.raises(InvitationError, match="Invalid invitation token"):
            await user_service.accept_invitation(
                db_session,
                token="nonexistent-token",
                password="pass",
                first_name="X",
                last_name="Y",
            )

    async def test_accept_rejects_expired_invitation(
        self, user_service, db_session, expired_invitation
    ):
        with pytest.raises(InvitationError, match="expired"):
            await user_service.accept_invitation(
                db_session,
                token="expired-token-xyz",
                password="pass",
                first_name="X",
                last_name="Y",
            )

    async def test_accept_rejects_already_accepted_invitation(
        self, user_service, db_session, pending_invitation
    ):
        # Accept once
        await user_service.accept_invitation(
            db_session,
            token="valid-token-abc123",
            password="secure-pass-123",
            first_name="New",
            last_name="User",
        )

        # Try to accept again
        with pytest.raises(InvitationError, match="already been used"):
            await user_service.accept_invitation(
                db_session,
                token="valid-token-abc123",
                password="other-pass",
                first_name="Other",
                last_name="Person",
            )

    async def test_accept_reactivates_existing_user(
        self, user_service, db_session, pending_invitation, active_user
    ):
        """If a user with the invitation email already exists, reactivate them."""
        # Change the invitation email to match active_user
        pending_invitation.email = active_user.email
        await db_session.flush()

        user = await user_service.accept_invitation(
            db_session,
            token="valid-token-abc123",
            password="new-password",
            first_name="Updated",
            last_name="Name",
        )

        assert user.id == active_user.id
        assert user.status == UserStatus.active
        assert user.first_name == "Updated"
        assert verify_password("new-password", user.password_hash)


# ---------------------------------------------------------------------------
# Deactivate tests
# ---------------------------------------------------------------------------


class TestDeactivate:
    """Test UserService.deactivate."""

    async def test_deactivate_sets_inactive_status(
        self, user_service, db_session, active_user, admin_user
    ):
        user = await user_service.deactivate(db_session, active_user.id, admin_user.id)
        assert user.status == UserStatus.inactive

    async def test_deactivate_retains_user_record(
        self, user_service, db_session, active_user, admin_user
    ):
        await user_service.deactivate(db_session, active_user.id, admin_user.id)

        # User record should still exist
        result = await db_session.execute(
            select(User).where(User.id == active_user.id)
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.email == "active@example.com"

    async def test_deactivate_writes_audit_event(
        self, user_service, db_session, active_user, admin_user
    ):
        from app.models.audit import AuditEvent

        await user_service.deactivate(db_session, active_user.id, admin_user.id)

        result = await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "user",
                AuditEvent.entity_id == active_user.id,
                AuditEvent.action == "deactivate",
            )
        )
        audit_event = result.scalar_one_or_none()
        assert audit_event is not None
        assert audit_event.actor_id == admin_user.id
        assert audit_event.old_value == "active"
        assert audit_event.new_value == "inactive"

    async def test_deactivate_raises_for_nonexistent_user(
        self, user_service, db_session, admin_user
    ):
        with pytest.raises(ValueError, match="User not found"):
            await user_service.deactivate(db_session, uuid.uuid4(), admin_user.id)


# ---------------------------------------------------------------------------
# Assign roles tests
# ---------------------------------------------------------------------------


class TestAssignRoles:
    """Test UserService.assign_roles."""

    async def test_assign_single_role(
        self, user_service, db_session, active_user, admin_user, site_coordinator_role
    ):
        study_id = uuid.uuid4()
        site_id = uuid.uuid4()
        assignments = [
            RoleAssignmentRequest(
                role_id=site_coordinator_role.id,
                study_id=study_id,
                site_id=site_id,
            )
        ]

        user = await user_service.assign_roles(
            db_session, active_user.id, assignments, admin_user.id
        )

        result = await db_session.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        )
        user_roles = result.scalars().all()
        assert len(user_roles) == 1
        assert user_roles[0].role_id == site_coordinator_role.id
        assert user_roles[0].study_id == study_id
        assert user_roles[0].site_id == site_id
        assert user_roles[0].assigned_by == admin_user.id

    async def test_assign_multiple_roles(
        self,
        user_service,
        db_session,
        active_user,
        admin_user,
        site_coordinator_role,
        data_manager_role,
    ):
        study_id = uuid.uuid4()
        assignments = [
            RoleAssignmentRequest(
                role_id=site_coordinator_role.id,
                study_id=study_id,
                site_id=uuid.uuid4(),
            ),
            RoleAssignmentRequest(
                role_id=data_manager_role.id,
                study_id=study_id,
            ),
        ]

        await user_service.assign_roles(
            db_session, active_user.id, assignments, admin_user.id
        )

        result = await db_session.execute(
            select(UserRole).where(UserRole.user_id == active_user.id)
        )
        user_roles = result.scalars().all()
        assert len(user_roles) == 2

    async def test_assign_roles_writes_audit_event(
        self, user_service, db_session, active_user, admin_user, site_coordinator_role
    ):
        from app.models.audit import AuditEvent

        assignments = [
            RoleAssignmentRequest(role_id=site_coordinator_role.id)
        ]

        await user_service.assign_roles(
            db_session, active_user.id, assignments, admin_user.id
        )

        result = await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "user",
                AuditEvent.entity_id == active_user.id,
                AuditEvent.action == "assign_roles",
            )
        )
        audit_event = result.scalar_one_or_none()
        assert audit_event is not None
        assert audit_event.actor_id == admin_user.id

    async def test_assign_roles_raises_for_nonexistent_user(
        self, user_service, db_session, admin_user, site_coordinator_role
    ):
        assignments = [
            RoleAssignmentRequest(role_id=site_coordinator_role.id)
        ]

        with pytest.raises(ValueError, match="User not found"):
            await user_service.assign_roles(
                db_session, uuid.uuid4(), assignments, admin_user.id
            )
