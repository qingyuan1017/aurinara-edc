"""Identity and access control models — users, roles, permissions, and invitations.

Satisfies Requirements:
  - 3.1: Users, roles with system/study/site scope, permissions, role-permission
          mapping, user-role assignments with study/site scope columns, and invitations.
  - 3.3: Role assignments carry study_id/site_id scope so Permission_Service can
          resolve study/site-level access.
  - 22.6: Indexed for efficient querying (email, role name, permission code,
           user_roles composite, invitation token).
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --- Enums ---


class UserStatus(enum.StrEnum):
    """User account status."""

    active = "active"
    inactive = "inactive"
    pending = "pending"


class ScopeLevel(enum.StrEnum):
    """Role scope level — determines where the role can be assigned."""

    system = "system"
    study = "study"
    site = "site"


class InvitationStatus(enum.StrEnum):
    """Invitation lifecycle status."""

    pending = "pending"
    accepted = "accepted"
    expired = "expired"


# --- Models ---


class User(Base):
    """Application user account."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Nullable for Cognito/OIDC users"
    )
    first_name: Mapped[str] = mapped_column(String(150), nullable=False)
    last_name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        String(20), nullable=False, default=UserStatus.pending
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="TOTP secret; nullable when MFA disabled"
    )
    last_activity: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reset_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, comment="Single-use password reset token"
    )
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Reset token expiry"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole", back_populates="user", foreign_keys="UserRole.user_id"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email!r}, status={self.status!r})>"


class Role(Base):
    """Authorization role with a defined scope level."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    scope_level: Mapped[ScopeLevel] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="True for built-in roles"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role"
    )
    user_roles: Mapped[list["UserRole"]] = relationship("UserRole", back_populates="role")

    def __repr__(self) -> str:
        return f"<Role(id={self.id}, name={self.name!r}, scope={self.scope_level!r})>"


class Permission(Base):
    """Granular permission code (e.g., 'form.enter', 'query.create')."""

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True, comment="e.g. form.enter"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="permission"
    )

    def __repr__(self) -> str:
        return f"<Permission(id={self.id}, code={self.code!r})>"


class RolePermission(Base):
    """Association between a role and a permission (many-to-many)."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(
        "Permission", back_populates="role_permissions"
    )

    def __repr__(self) -> str:
        return f"<RolePermission(role_id={self.role_id}, permission_id={self.permission_id})>"


class UserRole(Base):
    """User-to-role assignment with optional study/site scope."""

    __tablename__ = "user_roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    study_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="Non-null for study/site-scoped roles"
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="Non-null for site-scoped roles"
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="user_roles", foreign_keys=[user_id]
    )
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "study_id", "site_id", name="uq_user_role_scope"),
        Index("ix_user_roles_user_study", "user_id", "study_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserRole(id={self.id}, user_id={self.user_id}, role_id={self.role_id}, "
            f"study_id={self.study_id}, site_id={self.site_id})>"
        )


class Invitation(Base):
    """Pending user invitation to join with a specified role and scope."""

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[InvitationStatus] = mapped_column(
        String(20), nullable=False, default=InvitationStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    role: Mapped["Role"] = relationship("Role")
    inviter: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<Invitation(id={self.id}, email={self.email!r}, "
            f"status={self.status!r}, token={self.token[:8]}...)>"
        )
