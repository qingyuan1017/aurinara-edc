"""expand Designer form metadata and visit/folder/cycle structure

Adds the form, section, and item attributes required by the richer Designer
authoring surface.  Visit definitions gain an explicit definition kind and
folder/category/subtype metadata while preserving the existing visit table and
cycle membership edges.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE form_definitions
            ADD COLUMN form_type VARCHAR(50) NOT NULL DEFAULT 'simple',
            ADD COLUMN access_type VARCHAR(50) NOT NULL DEFAULT 'open_access',
            ADD COLUMN cdash_domain VARCHAR(50) NULL,
            ADD COLUMN cdash_label VARCHAR(255) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE form_sections
            ADD COLUMN label VARCHAR(500) NULL,
            ADD COLUMN is_label_only BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN output_to_dataset BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN help_text TEXT NULL,
            ADD COLUMN access_type VARCHAR(50) NOT NULL DEFAULT 'open_access'
        """
    )
    op.execute(
        """
        UPDATE form_sections
           SET label = name
         WHERE label IS NULL
        """
    )
    op.execute("ALTER TABLE form_sections ALTER COLUMN label SET NOT NULL")
    op.execute(
        """
        ALTER TABLE field_definitions
            ADD COLUMN question TEXT NULL,
            ADD COLUMN caption VARCHAR(500) NULL,
            ADD COLUMN text_align VARCHAR(20) NOT NULL DEFAULT 'left',
            ADD COLUMN record_id VARCHAR(255) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE visit_definitions
            ADD COLUMN definition_kind VARCHAR(20) NOT NULL DEFAULT 'visit',
            ADD COLUMN parent_folder_id UUID NULL,
            ADD COLUMN category VARCHAR(50) NULL,
            ADD COLUMN subtype VARCHAR(50) NULL,
            ADD CONSTRAINT fk_visit_definitions_parent_folder
                FOREIGN KEY (parent_folder_id)
                REFERENCES visit_definitions (id)
                ON DELETE SET NULL
        """
    )
    op.execute(
        """
        UPDATE visit_definitions
           SET definition_kind = 'cycle'
         WHERE visit_type = 'cycle'
        """
    )
    op.execute(
        "CREATE INDEX ix_visit_definitions_parent_folder_id ON visit_definitions (parent_folder_id)"
    )
    op.execute(
        "CREATE INDEX ix_visit_definitions_definition_kind ON visit_definitions (definition_kind)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_visit_definitions_definition_kind")
    op.execute("DROP INDEX IF EXISTS ix_visit_definitions_parent_folder_id")
    op.execute(
        """
        ALTER TABLE visit_definitions
            DROP CONSTRAINT IF EXISTS fk_visit_definitions_parent_folder,
            DROP COLUMN subtype,
            DROP COLUMN category,
            DROP COLUMN parent_folder_id,
            DROP COLUMN definition_kind
        """
    )
    op.execute(
        """
        ALTER TABLE field_definitions
            DROP COLUMN record_id,
            DROP COLUMN text_align,
            DROP COLUMN caption,
            DROP COLUMN question
        """
    )
    op.execute(
        """
        ALTER TABLE form_sections
            DROP COLUMN access_type,
            DROP COLUMN help_text,
            DROP COLUMN output_to_dataset,
            DROP COLUMN is_label_only,
            DROP COLUMN label
        """
    )
    op.execute(
        """
        ALTER TABLE form_definitions
            DROP COLUMN cdash_label,
            DROP COLUMN cdash_domain,
            DROP COLUMN access_type,
            DROP COLUMN form_type
        """
    )
