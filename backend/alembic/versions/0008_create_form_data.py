"""Create form data tables — form instances and field values.

Revision ID: 0008
Revises: 0007
Create Date: 2024-01-08 00:00:00.000000

Hybrid storage: form_instances.data_jsonb stores the full payload for fast
retrieval; normalized field_values rows support audit, query, SDV, review,
and export per-field.

Requirements:
  - 10.2: Form instance lifecycle statuses.
  - 22.3: Hybrid storage (JSONB + normalized rows).
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- form_instances ---
    op.create_table(
        "form_instances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "visit_instance_id",
            sa.Uuid(),
            sa.ForeignKey("visit_instances.id", ondelete="SET NULL"),
            nullable=True,
            comment="Nullable — form may exist outside a visit context",
        ),
        sa.Column(
            "form_definition_id",
            sa.Uuid(),
            sa.ForeignKey("form_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="Not Started",
        ),
        sa.Column(
            "data_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "submitted_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_form_instances_subject_id",
        "form_instances",
        ["subject_id"],
    )
    op.create_index(
        "ix_form_instances_visit_instance_id",
        "form_instances",
        ["visit_instance_id"],
    )
    op.create_index(
        "ix_form_instances_form_definition_id",
        "form_instances",
        ["form_definition_id"],
    )
    op.create_index(
        "ix_form_instances_status",
        "form_instances",
        ["status"],
    )

    # --- field_values ---
    op.create_table(
        "field_values",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "form_instance_id",
            sa.Uuid(),
            sa.ForeignKey("form_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_definition_id",
            sa.Uuid(),
            sa.ForeignKey("field_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "is_not_applicable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_field_values_form_instance_id",
        "field_values",
        ["form_instance_id"],
    )
    op.create_index(
        "ix_field_values_field_definition_id",
        "field_values",
        ["field_definition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_values_field_definition_id", table_name="field_values"
    )
    op.drop_index(
        "ix_field_values_form_instance_id", table_name="field_values"
    )
    op.drop_table("field_values")

    op.drop_index("ix_form_instances_status", table_name="form_instances")
    op.drop_index(
        "ix_form_instances_form_definition_id", table_name="form_instances"
    )
    op.drop_index(
        "ix_form_instances_visit_instance_id", table_name="form_instances"
    )
    op.drop_index(
        "ix_form_instances_subject_id", table_name="form_instances"
    )
    op.drop_table("form_instances")
