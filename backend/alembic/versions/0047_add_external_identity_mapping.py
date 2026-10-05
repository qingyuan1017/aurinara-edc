"""Add nullable external identity mapping to users.

Cognito authentication is keyed by the verified provider subject, never by a
mutable email address. Existing local users remain unchanged and can acquire a
mapping through the constrained legacy-link path after a verified Cognito ID
token is presented.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "external_identity_provider",
            sa.String(length=50),
            nullable=True,
            comment="External identity provider, e.g. cognito",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "external_subject",
            sa.String(length=255),
            nullable=True,
            comment="Immutable provider subject (Cognito sub)",
        ),
    )
    op.create_index(
        "ix_users_external_identity",
        "users",
        ["external_identity_provider", "external_subject"],
    )
    op.create_unique_constraint(
        "uq_users_external_identity",
        "users",
        ["external_identity_provider", "external_subject"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_external_identity", "users", type_="unique")
    op.drop_index("ix_users_external_identity", table_name="users")
    op.drop_column("users", "external_subject")
    op.drop_column("users", "external_identity_provider")
