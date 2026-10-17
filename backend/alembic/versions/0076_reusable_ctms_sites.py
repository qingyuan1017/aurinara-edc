"""Make CTMS Site master data reusable across Studies.

Revision ID: 0076
Revises: 0075
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | Sequence[str] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ctms_study_entity_assignments", sa.Column("site_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_ctms_study_entity_assignments_site_id",
        "ctms_study_entity_assignments",
        "sites",
        ["site_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        UPDATE ctms_study_entity_assignments AS assignment
        SET site_id = entity.canonical_site_id
        FROM ctms_managed_entities AS entity
        WHERE assignment.entity_id = entity.id
          AND entity.entity_type = 'site'
        """
    )
    op.create_unique_constraint(
        "uq_ctms_study_entity_assignment_site",
        "ctms_study_entity_assignments",
        ["site_id"],
    )
    op.drop_constraint(
        "uq_ctms_managed_entities_canonical_site",
        "ctms_managed_entities",
        type_="unique",
    )
    op.drop_constraint(
        "ctms_managed_entities_canonical_site_id_fkey",
        "ctms_managed_entities",
        type_="foreignkey",
    )
    op.drop_column("ctms_managed_entities", "canonical_site_id")


def downgrade() -> None:
    bind = op.get_bind()
    reused_site = bind.execute(
        sa.text(
            """
            SELECT entity_id
            FROM ctms_study_entity_assignments
            WHERE site_id IS NOT NULL AND deleted_at IS NULL
            GROUP BY entity_id
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if reused_site is not None:
        raise RuntimeError(
            "Cannot safely downgrade 0076 after a Site master has been assigned "
            "to more than one Study"
        )

    op.add_column("ctms_managed_entities", sa.Column("canonical_site_id", sa.Uuid()))
    op.create_foreign_key(
        "ctms_managed_entities_canonical_site_id_fkey",
        "ctms_managed_entities",
        "sites",
        ["canonical_site_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        UPDATE ctms_managed_entities AS entity
        SET canonical_site_id = assignment.site_id
        FROM ctms_study_entity_assignments AS assignment
        WHERE assignment.entity_id = entity.id
          AND entity.entity_type = 'site'
          AND assignment.site_id IS NOT NULL
        """
    )
    op.create_unique_constraint(
        "uq_ctms_managed_entities_canonical_site",
        "ctms_managed_entities",
        ["canonical_site_id"],
    )
    op.drop_constraint(
        "uq_ctms_study_entity_assignment_site",
        "ctms_study_entity_assignments",
        type_="unique",
    )
    op.drop_constraint(
        "fk_ctms_study_entity_assignments_site_id",
        "ctms_study_entity_assignments",
        type_="foreignkey",
    )
    op.drop_column("ctms_study_entity_assignments", "site_id")
