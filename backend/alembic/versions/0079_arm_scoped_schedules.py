"""Move treatment-arm visit/form membership into arm-scoped SoAs.

Revision ID: 0079
Revises: 0078
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | Sequence[str] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedule_of_assessment",
        sa.Column("arm_definition_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_schedule_of_assessment_arm_definition_id",
        "schedule_of_assessment",
        "arm_definitions",
        ["arm_definition_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_schedule_of_assessment_arm_definition_id",
        "schedule_of_assessment",
        ["arm_definition_id"],
    )

    # Preserve legacy arm membership by materializing one complete SoA per arm.
    # Each arm schedule receives only entries whose visit belonged to that arm.
    op.execute(
        """
        WITH latest_common AS (
            SELECT DISTINCT ON (design_version_id)
                   id, design_version_id
              FROM schedule_of_assessment
             WHERE deleted_at IS NULL
               AND arm_definition_id IS NULL
             ORDER BY design_version_id, created_at DESC, id DESC
        ),
        inserted AS (
            INSERT INTO schedule_of_assessment (
                id, design_version_id, arm_definition_id,
                created_at, updated_at, deleted_at
            )
            SELECT gen_random_uuid(), a.study_version_id, a.id,
                   now(), NULL, NULL
              FROM arm_definitions a
              JOIN latest_common lc
                ON lc.design_version_id = a.study_version_id
             WHERE a.deleted_at IS NULL
            RETURNING id, design_version_id, arm_definition_id
        )
        INSERT INTO schedule_of_assessment_entries (
            id, schedule_of_assessment_id, form_definition_id,
            procedure_name, visit_definition_id, display_order,
            created_at, updated_at, deleted_at
        )
        SELECT gen_random_uuid(), target.id, entry.form_definition_id,
               entry.procedure_name, entry.visit_definition_id, entry.display_order,
               now(), NULL, NULL
          FROM inserted target
          JOIN latest_common source
            ON source.design_version_id = target.design_version_id
          JOIN schedule_of_assessment_entries entry
            ON entry.schedule_of_assessment_id = source.id
           AND entry.deleted_at IS NULL
          JOIN arm_definition_visits membership
            ON membership.arm_definition_id = target.arm_definition_id
           AND membership.visit_definition_id = entry.visit_definition_id
        """
    )

    op.create_index(
        "uq_schedule_of_assessment_common_live",
        "schedule_of_assessment",
        ["design_version_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND arm_definition_id IS NULL"),
    )
    op.create_index(
        "uq_schedule_of_assessment_arm_live",
        "schedule_of_assessment",
        ["design_version_id", "arm_definition_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND arm_definition_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Reconstruct the old visit membership as faithfully as the scoped SoAs
    # permit before removing the arm-specific schedules.
    op.execute(
        """
        INSERT INTO arm_definition_visits (arm_definition_id, visit_definition_id)
        SELECT DISTINCT soa.arm_definition_id, entry.visit_definition_id
          FROM schedule_of_assessment soa
          JOIN schedule_of_assessment_entries entry
            ON entry.schedule_of_assessment_id = soa.id
         WHERE soa.arm_definition_id IS NOT NULL
           AND soa.deleted_at IS NULL
           AND entry.deleted_at IS NULL
           AND entry.visit_definition_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DELETE FROM schedule_of_assessment WHERE arm_definition_id IS NOT NULL")
    op.drop_index(
        "uq_schedule_of_assessment_arm_live",
        table_name="schedule_of_assessment",
    )
    op.drop_index(
        "uq_schedule_of_assessment_common_live",
        table_name="schedule_of_assessment",
    )
    op.drop_index(
        "ix_schedule_of_assessment_arm_definition_id",
        table_name="schedule_of_assessment",
    )
    op.drop_constraint(
        "fk_schedule_of_assessment_arm_definition_id",
        "schedule_of_assessment",
        type_="foreignkey",
    )
    op.drop_column("schedule_of_assessment", "arm_definition_id")
