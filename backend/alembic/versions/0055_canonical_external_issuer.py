"""Store the canonical OIDC issuer for external user identities.

Revision ID: 0055
Revises: 0054
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("external_issuer", sa.String(length=512)))
    op.drop_index("ix_users_external_identity", table_name="users")
    op.drop_constraint("uq_users_external_identity", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_external_identity", "users", ["external_issuer", "external_subject"]
    )
    op.create_index(
        "ix_users_external_identity",
        "users",
        ["external_issuer", "external_subject"],
    )
    op.add_column("file_attachments", sa.Column("platform_reference_id", sa.Uuid()))
    op.create_unique_constraint(
        "uq_file_attachments_platform_reference_id",
        "file_attachments",
        ["platform_reference_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_file_attachments_platform_reference_id", "file_attachments", type_="unique"
    )
    op.drop_column("file_attachments", "platform_reference_id")
    op.drop_index("ix_users_external_identity", table_name="users")
    op.drop_constraint("uq_users_external_identity", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_external_identity",
        "users",
        ["external_identity_provider", "external_subject"],
    )
    op.create_index(
        "ix_users_external_identity",
        "users",
        ["external_identity_provider", "external_subject"],
    )
    op.drop_column("users", "external_issuer")
