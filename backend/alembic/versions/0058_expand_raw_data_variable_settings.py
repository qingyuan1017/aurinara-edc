"""expand raw-data field suffix configuration

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE raw_data_variable_settings
            ADD COLUMN field_definition_id UUID NULL,
            ADD COLUMN year_suffix VARCHAR(50) NULL,
            ADD COLUMN month_suffix VARCHAR(50) NULL,
            ADD COLUMN day_suffix VARCHAR(50) NULL,
            ADD CONSTRAINT fk_raw_data_variable_field
                FOREIGN KEY (field_definition_id)
                REFERENCES field_definitions (id)
                ON DELETE CASCADE,
            ADD CONSTRAINT uq_raw_data_variable_field
                UNIQUE (field_definition_id)
        """
    )
    op.execute(
        "CREATE INDEX ix_raw_data_variable_settings_field_definition_id "
        "ON raw_data_variable_settings (field_definition_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_raw_data_variable_settings_field_definition_id")
    op.execute(
        """
        ALTER TABLE raw_data_variable_settings
            DROP CONSTRAINT IF EXISTS uq_raw_data_variable_field,
            DROP CONSTRAINT IF EXISTS fk_raw_data_variable_field,
            DROP COLUMN day_suffix,
            DROP COLUMN month_suffix,
            DROP COLUMN year_suffix,
            DROP COLUMN field_definition_id
        """
    )
