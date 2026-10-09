"""Enforce not-null on design_version_id after backfill.

Revision ID: 0050
Revises: 0049

Part of the Designer / EDC refactor (Phase 3). Migration 0048 added the nullable
``design_version_id`` columns and migration 0049 backfilled them from each
record's owning Subject (with a study-current-published fallback). This
migration makes those columns NOT NULL so every operational record is
permanently bound to a published design version, matching how
``subjects.study_version_id`` is already declared not-null.

This step only tightens a constraint; it reads and writes no stored values
(R11.2). If any row is still NULL at this point, the ALTER will fail loudly —
that is intentional, surfacing untraceable edge cases rather than silently
binding them to a wrong version.

Requirements:
  - 11.2: Not-null is enforced only after the backfill completes.
  - 2.7 / 7.3: Every operational record binds to exactly one published design
    version.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The nine operational tables whose design_version_id was backfilled in 0049.
# ``subjects`` is excluded: its binding (study_version_id) was already not-null.
_BINDING_TABLES: tuple[str, ...] = (
    "visit_instances",
    "form_instances",
    "form_records",
    "field_values",
    "queries",
    "sdv_status",
    "review_status",
    "freezes_locks",
    "signatures",
)


def upgrade() -> None:
    for table in _BINDING_TABLES:
        op.alter_column(
            table,
            "design_version_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )


def downgrade() -> None:
    for table in reversed(_BINDING_TABLES):
        op.alter_column(
            table,
            "design_version_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
