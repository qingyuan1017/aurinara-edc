"""Add nullable design_version_id binding columns to operational tables.

Revision ID: 0048
Revises: 0047

Part of the Designer / EDC refactor (Phase 3). Each operational table that does
not already carry a design-version binding gains a NULLABLE ``design_version_id``
column with a foreign key to ``study_versions.id`` and a supporting index. This
change is purely additive: no renames, no data changes, and no not-null
constraint yet (not-null is enforced after backfill in a follow-up migration).

``subjects`` already binds to a published design through its existing
``study_version_id`` column, so it is intentionally left untouched here.

Requirements:
  - 11.2: Reassign operational records to the EDC_Module without altering their
    stored values; binding columns are added nullable and backfilled before
    not-null is enforced.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Operational tables lacking a design-version binding, each mapped to the name
# of the supporting index created for the new column. ``subjects`` is excluded:
# its existing not-null ``study_version_id`` already binds it to a design.
_BINDING_TABLES: dict[str, str] = {
    "visit_instances": "ix_visit_instances_design_version_id",
    "form_instances": "ix_form_instances_design_version_id",
    "form_records": "ix_form_records_design_version_id",
    "field_values": "ix_field_values_design_version_id",
    "queries": "ix_queries_design_version_id",
    "sdv_status": "ix_sdv_status_design_version_id",
    "review_status": "ix_review_status_design_version_id",
    "freezes_locks": "ix_freezes_locks_design_version_id",
    "signatures": "ix_signatures_design_version_id",
}


def upgrade() -> None:
    for table, index_name in _BINDING_TABLES.items():
        op.add_column(
            table,
            sa.Column(
                "design_version_id",
                sa.Uuid(),
                sa.ForeignKey("study_versions.id", ondelete="RESTRICT"),
                nullable=True,
                comment="Binds this operational record to a published design "
                "version (nullable until backfill enforces not-null)",
            ),
        )
        op.create_index(index_name, table, ["design_version_id"])


def downgrade() -> None:
    for table, index_name in reversed(list(_BINDING_TABLES.items())):
        op.drop_index(index_name, table_name=table)
        op.drop_column(table, "design_version_id")
