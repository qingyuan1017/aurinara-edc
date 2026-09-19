"""Add outcome and affected-field context to validation results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "validation_results",
        sa.Column(
            "outcome",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'failed'"),
            comment="One of: passed, failed",
        ),
    )
    op.add_column(
        "validation_results",
        sa.Column(
            "record_id",
            sa.Uuid(),
            sa.ForeignKey("form_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "validation_results",
        sa.Column(
            "field_definition_id",
            sa.Uuid(),
            sa.ForeignKey("field_definitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_validation_results_outcome", "validation_results", ["outcome"]
    )


def downgrade() -> None:
    op.drop_index("ix_validation_results_outcome", table_name="validation_results")
    op.drop_column("validation_results", "field_definition_id")
    op.drop_column("validation_results", "record_id")
    op.drop_column("validation_results", "outcome")
