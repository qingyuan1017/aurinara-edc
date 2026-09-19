"""Add sanitized remediation details to CTMS failure and conflict records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ctms_failed_events",
        sa.Column("sanitized_details_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column("ctms_coordination_conflicts", sa.Column("field_path", sa.String(128), nullable=True))
    op.add_column("ctms_coordination_conflicts", sa.Column("policy", sa.String(100), nullable=True))
    op.add_column(
        "ctms_coordination_conflicts",
        sa.Column("sanitized_details_json", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("ctms_coordination_conflicts", "sanitized_details_json")
    op.drop_column("ctms_coordination_conflicts", "policy")
    op.drop_column("ctms_coordination_conflicts", "field_path")
    op.drop_column("ctms_failed_events", "sanitized_details_json")
