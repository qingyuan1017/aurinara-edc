"""subject phase transitions (directed phase-to-phase edges)

Adds the new Designer-owned ``subject_phase_transitions`` table: a typed,
self-referential edge between two ``subject_phase_definitions`` rows within one
``Design_Version``. The edge is self-guarded (a phase cannot transition to
itself) and a ``(design_version_id, from_phase_id, to_phase_id)`` triple is
unique. The table is soft-deletable (nullable ``deleted_at``) for regulated
record retention.

This migration is purely additive: one new table and three indexes. No existing
table or column is changed, so the downgrade simply drops the table.

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-10
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | None = None
depends_on: str | None = None


# ---------------------------------------------------------------------------
# upgrade() ordered DDL (raw-DDL style, mirroring 0052._CREATE_NEW_TABLES)
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
    CREATE TABLE subject_phase_transitions (
        id                   UUID NOT NULL,
        design_version_id    UUID NOT NULL,
        from_phase_id        UUID NOT NULL,
        to_phase_id          UUID NOT NULL,
        label                VARCHAR(255) NULL,
        condition_expression TEXT NULL,
        created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        updated_at           TIMESTAMP WITH TIME ZONE NULL,
        deleted_at           TIMESTAMP WITH TIME ZONE NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_subject_phase_transition_not_self
            CHECK (from_phase_id <> to_phase_id),
        CONSTRAINT uq_subject_phase_transition
            UNIQUE (design_version_id, from_phase_id, to_phase_id),
        FOREIGN KEY (design_version_id) REFERENCES study_versions (id) ON DELETE CASCADE,
        FOREIGN KEY (from_phase_id) REFERENCES subject_phase_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY (to_phase_id)   REFERENCES subject_phase_definitions (id) ON DELETE CASCADE
    )
"""

_CREATE_INDEXES = [
    """
    CREATE INDEX ix_subject_phase_transitions_design_version_id
        ON subject_phase_transitions (design_version_id)
    """,
    """
    CREATE INDEX ix_subject_phase_transitions_from_phase_id
        ON subject_phase_transitions (from_phase_id)
    """,
    """
    CREATE INDEX ix_subject_phase_transitions_to_phase_id
        ON subject_phase_transitions (to_phase_id)
    """,
]


def upgrade() -> None:
    op.execute(_CREATE_TABLE)
    for ddl in _CREATE_INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subject_phase_transitions CASCADE")
