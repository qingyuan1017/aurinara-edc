"""Persist ODM identities for subject phases and transitions.

Revision ID: 0083
Revises: 0082
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | Sequence[str] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subject_phase_definitions",
        sa.Column("odm_oid", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "subject_phase_transitions",
        sa.Column("odm_oid", sa.String(length=255), nullable=True),
    )
    op.execute(
        "UPDATE subject_phase_definitions "
        "SET odm_oid = 'PH.' || upper(replace(id::text, '-', '')) "
        "WHERE odm_oid IS NULL"
    )
    op.execute(
        "UPDATE subject_phase_transitions "
        "SET odm_oid = 'PHT.' || upper(replace(id::text, '-', '')) "
        "WHERE odm_oid IS NULL"
    )
    op.alter_column("subject_phase_definitions", "odm_oid", nullable=False)
    op.alter_column("subject_phase_transitions", "odm_oid", nullable=False)
    op.create_unique_constraint(
        "uq_subject_phase_definition_oid_per_version",
        "subject_phase_definitions",
        ["design_version_id", "odm_oid"],
    )
    op.create_unique_constraint(
        "uq_subject_phase_transition_oid_per_version",
        "subject_phase_transitions",
        ["design_version_id", "odm_oid"],
    )
    op.create_index(
        "ix_subject_phase_definitions_odm_oid",
        "subject_phase_definitions",
        ["odm_oid"],
    )
    op.create_index(
        "ix_subject_phase_transitions_odm_oid",
        "subject_phase_transitions",
        ["odm_oid"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subject_phase_transitions_odm_oid",
        table_name="subject_phase_transitions",
    )
    op.drop_index(
        "ix_subject_phase_definitions_odm_oid",
        table_name="subject_phase_definitions",
    )
    op.drop_constraint(
        "uq_subject_phase_transition_oid_per_version",
        "subject_phase_transitions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_subject_phase_definition_oid_per_version",
        "subject_phase_definitions",
        type_="unique",
    )
    op.drop_column("subject_phase_transitions", "odm_oid")
    op.drop_column("subject_phase_definitions", "odm_oid")
