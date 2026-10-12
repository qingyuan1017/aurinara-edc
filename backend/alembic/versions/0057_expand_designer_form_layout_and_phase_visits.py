"""expand Designer form layout and subject phase visit associations

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE form_definitions
            RENAME COLUMN cdash_domain TO domain
        """
    )
    op.execute(
        """
        ALTER TABLE field_definitions
            ADD COLUMN crf_id VARCHAR(255) NULL,
            ADD COLUMN odm_id VARCHAR(255) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE form_definitions
            RENAME COLUMN cdash_label TO label
        """
    )
    op.execute(
        """
        ALTER TABLE form_definitions
            ADD COLUMN grid_rows INTEGER NULL,
            ADD COLUMN grid_columns INTEGER NULL,
            ADD COLUMN header_name VARCHAR(255) NULL,
            ADD COLUMN detail_name VARCHAR(255) NULL,
            ADD COLUMN detail_type VARCHAR(20) NULL,
            ADD COLUMN show_variable_name BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN show_crf_id BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN show_odm_id BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    op.execute(
        """
        CREATE TABLE subject_phase_visit_definitions (
            id UUID PRIMARY KEY,
            subject_phase_definition_id UUID NOT NULL,
            visit_definition_id UUID NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT fk_subject_phase_visit_phase
                FOREIGN KEY (subject_phase_definition_id)
                REFERENCES subject_phase_definitions (id)
                ON DELETE CASCADE,
            CONSTRAINT fk_subject_phase_visit_visit
                FOREIGN KEY (visit_definition_id)
                REFERENCES visit_definitions (id)
                ON DELETE CASCADE,
            CONSTRAINT uq_subject_phase_visit
                UNIQUE (subject_phase_definition_id, visit_definition_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_subject_phase_visit_phase_id "
        "ON subject_phase_visit_definitions (subject_phase_definition_id)"
    )
    op.execute(
        "CREATE INDEX ix_subject_phase_visit_visit_id "
        "ON subject_phase_visit_definitions (visit_definition_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_subject_phase_visit_visit_id")
    op.execute("DROP INDEX IF EXISTS ix_subject_phase_visit_phase_id")
    op.execute("DROP TABLE subject_phase_visit_definitions")
    op.execute(
        """
        ALTER TABLE field_definitions
            DROP COLUMN odm_id,
            DROP COLUMN crf_id
        """
    )
    op.execute(
        """
        ALTER TABLE form_definitions
            DROP COLUMN show_odm_id,
            DROP COLUMN show_crf_id,
            DROP COLUMN show_variable_name,
            DROP COLUMN detail_type,
            DROP COLUMN detail_name,
            DROP COLUMN header_name,
            DROP COLUMN grid_columns,
            DROP COLUMN grid_rows
        """
    )
    op.execute("ALTER TABLE form_definitions RENAME COLUMN label TO cdash_label")
    op.execute("ALTER TABLE form_definitions RENAME COLUMN domain TO cdash_domain")
