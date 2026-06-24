"""Create identity tables: users, roles, permissions, role_permissions, user_roles, invitations.

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000

Requirements:
  - 3.1: Users, roles (system/study/site scope), permissions, role-permission mapping,
          user-role assignments with study/site scope columns, and invitations.
  - 3.3: Role assignments carry study_id/site_id scope for permission resolution.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column(
            "password_hash",
            sa.String(255),
            nullable=True,
            comment="Nullable for Cognito/OIDC users",
        ),
        sa.Column("first_name", sa.String(150), nullable=False),
        sa.Column("last_name", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "mfa_secret",
            sa.String(255),
            nullable=True,
            comment="TOTP secret; nullable when MFA disabled",
        ),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- roles ---
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("scope_level", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True for built-in roles",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    # --- permissions ---
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "code",
            sa.String(100),
            unique=True,
            nullable=False,
            comment="e.g. form.enter",
        ),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    # --- role_permissions (association) ---
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.Uuid(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            sa.Uuid(),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # --- user_roles (with study/site scope) ---
    op.create_table(
        "user_roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Uuid(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "study_id",
            sa.Uuid(),
            nullable=True,
            comment="Non-null for study/site-scoped roles",
        ),
        sa.Column(
            "site_id",
            sa.Uuid(),
            nullable=True,
            comment="Non-null for site-scoped roles",
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "assigned_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("user_id", "role_id", "study_id", "site_id", name="uq_user_role_scope"),
    )
    op.create_index("ix_user_roles_user_study", "user_roles", ["user_id", "study_id"])

    # --- invitations ---
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token", sa.String(255), unique=True, nullable=False),
        sa.Column(
            "role_id",
            sa.Uuid(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column(
            "invited_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invitations_token", "invitations", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invitations_token", table_name="invitations")
    op.drop_table("invitations")

    op.drop_index("ix_user_roles_user_study", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_table("role_permissions")

    op.drop_index("ix_permissions_code", table_name="permissions")
    op.drop_table("permissions")

    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_table("roles")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
