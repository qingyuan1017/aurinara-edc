"""Create form metadata tables — form definitions, sections, fields, code lists.

Revision ID: 0007
Revises: 0006
Create Date: 2024-01-07 00:00:00.000000

Form versioning is achieved through the ``study_version_id`` relationship on
``form_definitions``; there is no separate ``form_versions`` table.

Requirements:
  - 9.1: Form definitions within a study version.
  - 9.2: Form sections and field definitions, ordered for display.
  - 9.5: Code lists and code list items referenced by fields.
  - 22.1: UUID primary keys.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- form_definitions ---
    op.create_table(
        "form_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "form_code",
            sa.String(50),
            nullable=False,
            comment='e.g. "AE", "CM", "DM"',
        ),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_repeating",
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
    )
    op.create_index(
        "ix_form_definitions_study_version_id",
        "form_definitions",
        ["study_version_id"],
    )

    # --- form_sections ---
    op.create_table(
        "form_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "form_definition_id",
            sa.Uuid(),
            sa.ForeignKey("form_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_form_sections_form_definition_id",
        "form_sections",
        ["form_definition_id"],
    )

    # --- codelists ---
    op.create_table(
        "codelists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
    )
    op.create_index(
        "ix_codelists_study_version_id",
        "codelists",
        ["study_version_id"],
    )

    # --- codelist_items ---
    op.create_table(
        "codelist_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "codelist_id",
            sa.Uuid(),
            sa.ForeignKey("codelists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "normal_low",
            sa.Numeric(),
            nullable=True,
            comment="Lab reference range lower bound",
        ),
        sa.Column(
            "normal_high",
            sa.Numeric(),
            nullable=True,
            comment="Lab reference range upper bound",
        ),
    )
    op.create_index(
        "ix_codelist_items_codelist_id",
        "codelist_items",
        ["codelist_id"],
    )

    # --- field_definitions ---
    op.create_table(
        "field_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "form_section_id",
            sa.Uuid(),
            sa.ForeignKey("form_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("variable_name", sa.String(255), nullable=False),
        sa.Column(
            "control_type",
            sa.String(50),
            nullable=False,
            comment=(
                "text, textarea, integer, decimal, date, datetime, time, radio, "
                "checkbox, dropdown, multi-select, boolean, file_upload, "
                "calculated, repeating_table, coded_term"
            ),
        ),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "codelist_id",
            sa.Uuid(),
            sa.ForeignKey("codelists.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("help_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("min_value", sa.Numeric(), nullable=True),
        sa.Column("max_value", sa.Numeric(), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("decimal_precision", sa.Integer(), nullable=True),
        sa.Column("regex_validation", sa.Text(), nullable=True),
        sa.Column(
            "visibility_rule",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_calculated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("calculation_expression", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_field_definitions_form_section_id",
        "field_definitions",
        ["form_section_id"],
    )
    op.create_index(
        "ix_field_definitions_codelist_id",
        "field_definitions",
        ["codelist_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_field_definitions_codelist_id", table_name="field_definitions"
    )
    op.drop_index(
        "ix_field_definitions_form_section_id", table_name="field_definitions"
    )
    op.drop_table("field_definitions")

    op.drop_index("ix_codelist_items_codelist_id", table_name="codelist_items")
    op.drop_table("codelist_items")

    op.drop_index("ix_codelists_study_version_id", table_name="codelists")
    op.drop_table("codelists")

    op.drop_index(
        "ix_form_sections_form_definition_id", table_name="form_sections"
    )
    op.drop_table("form_sections")

    op.drop_index(
        "ix_form_definitions_study_version_id", table_name="form_definitions"
    )
    op.drop_table("form_definitions")
