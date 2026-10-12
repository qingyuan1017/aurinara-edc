"""add subject phase types and operational tracking

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Existing phases already allow visit membership, so ``common`` preserves
    # their behavior while introducing the typed workflow additively.
    op.execute(
        """
        ALTER TABLE subject_phase_definitions
            ADD COLUMN phase_type VARCHAR(30) NOT NULL DEFAULT 'common',
            ADD CONSTRAINT ck_subject_phase_definition_type
                CHECK (phase_type IN (
                    'registered', 'screen_failure', 'common', 'complete', 'arm'
                ))
        """
    )
    op.execute(
        """
        ALTER TABLE subjects
            ADD COLUMN current_phase_definition_id UUID NULL,
            ADD COLUMN arm_definition_id UUID NULL,
            ADD CONSTRAINT fk_subject_current_phase_definition
                FOREIGN KEY (current_phase_definition_id)
                REFERENCES subject_phase_definitions (id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT fk_subject_arm_definition
                FOREIGN KEY (arm_definition_id)
                REFERENCES arm_definitions (id)
                ON DELETE RESTRICT
        """
    )
    op.execute(
        "CREATE INDEX ix_subjects_current_phase_definition_id "
        "ON subjects (current_phase_definition_id)"
    )
    op.execute(
        "CREATE INDEX ix_subjects_arm_definition_id ON subjects (arm_definition_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_subjects_arm_definition_id")
    op.execute("DROP INDEX IF EXISTS ix_subjects_current_phase_definition_id")
    op.execute(
        """
        ALTER TABLE subjects
            DROP CONSTRAINT IF EXISTS fk_subject_arm_definition,
            DROP CONSTRAINT IF EXISTS fk_subject_current_phase_definition,
            DROP COLUMN arm_definition_id,
            DROP COLUMN current_phase_definition_id
        """
    )
    op.execute(
        """
        ALTER TABLE subject_phase_definitions
            DROP CONSTRAINT IF EXISTS ck_subject_phase_definition_type,
            DROP COLUMN phase_type
        """
    )
