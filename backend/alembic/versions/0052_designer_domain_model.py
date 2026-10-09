"""designer domain-model refactor (cycle folds into visit; arm/visit mapping;
raw-data label/suffix; CRF blinding; form/visit dependencies)

Folds the Designer ``cycle_definitions`` concept into ``visit_definitions`` via a
``visit_type = 'cycle'`` discriminator and explicit nullable cycle columns, then
drops the deprecated cycle tables. Collapses the parallel SoA visit/cycle refs
into a single ``visit_definition_id``. Adds a new ``arm_definition_visits``
association, first-class raw-data ``label``/``suffix`` columns, CRF ``blinded`` /
``unblind_role`` columns, and two self-referential dependency tables
(``form_definition_dependencies`` / ``visit_definition_dependencies``).

This migration is ADDITIVE-first and value-preserving: existing (non-deleted)
``cycle_definitions`` rows and their ``cycle_definition_visits`` membership are
migrated into ``visit_definitions`` (id-preserving) and
``visit_definition_dependencies`` (as ``'cycle_member'`` edges) before the
deprecated cycle tables are dropped. No table or column is renamed. No
operational table (subjects / visit_instances / form_instances / CTMS / PV)
holds an FK to the dropped cycle tables, so dropping them is safe.

``visit_type`` gains a ``'cycle'`` value (migrated cycles) and a server default
of ``'visit'``; no pre-existing row carries ``'visit'`` or ``'cycle'``, so
existing ``visit_type`` filters are unaffected for historical data.

Downgrade is best-effort and NOT fully reversible (documented up front):
  (a) soft-deleted cycles were not migrated up and cannot be restored;
  (b) ``repeat_min`` / ``repeat_max`` / ``cycle_length`` authored on cycles after
      upgrade are lost (old ``cycle_definitions`` had no such columns);
  (c) form/visit dependency rows other than ``'cycle_member'`` are dropped (no
      0051 home);
  (d) the ``visit_number`` / ``is_required`` synthesized onto migrated cycle rows
      are discarded (``cycle_definitions`` has no such columns; harmless);
  (e) the SoA split restoration keys off ``visit_definition_id IN (SELECT id FROM
      cycle_definitions)`` — exact for non-deleted cycles only because upgrade
      preserved the original cycle UUIDs as the visit ids (id preservation is
      mandatory, not an optimization).

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-09
"""

from __future__ import annotations

import uuid

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | None = None
depends_on: str | None = None


# ---------------------------------------------------------------------------
# upgrade() ordered DDL
# ---------------------------------------------------------------------------

_ADD_VISIT_COLUMNS = [
    """
    ALTER TABLE visit_definitions
        ADD COLUMN repeat_min   INTEGER NULL,
        ADD COLUMN repeat_max   INTEGER NULL,
        ADD COLUMN cycle_length INTEGER NULL
    """,
    "ALTER TABLE visit_definitions ALTER COLUMN visit_type SET DEFAULT 'visit'",
    "CREATE INDEX ix_visit_definitions_visit_type ON visit_definitions (visit_type)",
]

_CREATE_NEW_TABLES = [
    """
    CREATE TABLE arm_definition_visits (
        arm_definition_id   UUID NOT NULL,
        visit_definition_id UUID NOT NULL,
        PRIMARY KEY (arm_definition_id, visit_definition_id),
        FOREIGN KEY (arm_definition_id)   REFERENCES arm_definitions (id)   ON DELETE CASCADE,
        FOREIGN KEY (visit_definition_id) REFERENCES visit_definitions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX ix_arm_definition_visits_visit_definition_id
        ON arm_definition_visits (visit_definition_id)
    """,
    """
    CREATE TABLE form_definition_dependencies (
        id                            UUID NOT NULL,
        form_definition_id            UUID NOT NULL,
        depends_on_form_definition_id UUID NOT NULL,
        dependency_type               VARCHAR(50) NOT NULL DEFAULT 'prerequisite',
        condition_expression          TEXT NULL,
        created_at                    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (id),
        CONSTRAINT ck_form_dependency_not_self
            CHECK (form_definition_id <> depends_on_form_definition_id),
        CONSTRAINT uq_form_dependency UNIQUE (form_definition_id, depends_on_form_definition_id, dependency_type),
        FOREIGN KEY (form_definition_id)            REFERENCES form_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY (depends_on_form_definition_id) REFERENCES form_definitions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX ix_form_definition_dependencies_form_definition_id
        ON form_definition_dependencies (form_definition_id)
    """,
    """
    CREATE INDEX ix_form_definition_dependencies_depends_on
        ON form_definition_dependencies (depends_on_form_definition_id)
    """,
    """
    CREATE TABLE visit_definition_dependencies (
        id                             UUID NOT NULL,
        visit_definition_id            UUID NOT NULL,
        depends_on_visit_definition_id UUID NOT NULL,
        dependency_type                VARCHAR(50) NOT NULL DEFAULT 'prerequisite',
        condition_expression           TEXT NULL,
        created_at                     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (id),
        CONSTRAINT ck_visit_dependency_not_self
            CHECK (visit_definition_id <> depends_on_visit_definition_id),
        CONSTRAINT uq_visit_dependency UNIQUE (visit_definition_id, depends_on_visit_definition_id, dependency_type),
        FOREIGN KEY (visit_definition_id)            REFERENCES visit_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY (depends_on_visit_definition_id) REFERENCES visit_definitions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX ix_visit_definition_dependencies_visit_definition_id
        ON visit_definition_dependencies (visit_definition_id)
    """,
    """
    CREATE INDEX ix_visit_definition_dependencies_depends_on
        ON visit_definition_dependencies (depends_on_visit_definition_id)
    """,
]

# Insert one visit row per non-deleted cycle, PRESERVING the cycle UUID as the
# visit id and synthesizing visit_number / visit_type='cycle' / is_required.
_MIGRATE_CYCLE_VISITS = """
    INSERT INTO visit_definitions (
        id, study_version_id, name, visit_number, visit_type,
        target_day, window_before, window_after,
        display_order, is_required, created_at,
        repeat_min, repeat_max, cycle_length
    )
    SELECT
        c.id,
        c.study_version_id,
        c.name,
        (SELECT COALESCE(MAX(v.visit_number), 0)
           FROM visit_definitions v
          WHERE v.study_version_id = c.study_version_id)
        + ROW_NUMBER() OVER (
              PARTITION BY c.study_version_id ORDER BY c.display_order, c.id),
        'cycle',
        NULL, NULL, NULL,
        c.display_order,
        TRUE,
        c.created_at,
        NULL, NULL, NULL
    FROM cycle_definitions c
    WHERE c.deleted_at IS NULL
"""

# Repoint cycle-referencing SoA entries onto the migrated visit row (same UUID).
_REPOINT_SOA = """
    UPDATE schedule_of_assessment_entries
       SET visit_definition_id = cycle_definition_id
     WHERE cycle_definition_id IS NOT NULL
       AND visit_definition_id IS NULL
"""

_DROP_SOA_CYCLE_COLUMN = [
    "DROP INDEX IF EXISTS ix_schedule_of_assessment_entries_cycle_definition_id",
    "ALTER TABLE schedule_of_assessment_entries DROP COLUMN cycle_definition_id",
]

_DROP_CYCLE_TABLES = [
    "DROP TABLE IF EXISTS cycle_definition_visits CASCADE",
    "DROP TABLE IF EXISTS cycle_definitions CASCADE",
]

_ADD_RAW_DATA_COLUMNS = """
    ALTER TABLE raw_data_variable_settings
        ADD COLUMN label  VARCHAR(255) NULL,
        ADD COLUMN suffix VARCHAR(50)  NULL
"""

_ADD_CRF_COLUMNS = """
    ALTER TABLE crf_access_definitions
        ADD COLUMN blinded      BOOLEAN      NOT NULL DEFAULT FALSE,
        ADD COLUMN unblind_role VARCHAR(100) NULL
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add cycle columns to visit_definitions and the discriminator index.
    for ddl in _ADD_VISIT_COLUMNS:
        op.execute(ddl)

    # 2-4. Create the new association + dependency tables (before any inserts
    # that reference them).
    for ddl in _CREATE_NEW_TABLES:
        op.execute(ddl)

    # 5. Migrate non-deleted cycles into visit_definitions (id-preserving).
    op.execute(_MIGRATE_CYCLE_VISITS)

    # 6. Preserve cycle membership as 'cycle_member' visit dependency edges.
    # cycle_definition_id is now a visit_definitions.id (step 5 preserved ids).
    membership = bind.execute(
        text(
            "SELECT cdv.visit_definition_id AS member_visit_id, "
            "       cdv.cycle_definition_id AS cycle_visit_id "
            "FROM cycle_definition_visits cdv "
            "JOIN cycle_definitions c ON c.id = cdv.cycle_definition_id "
            "WHERE c.deleted_at IS NULL"
        )
    ).fetchall()
    if membership:
        rows = [
            {
                "id": str(uuid.uuid4()),
                "visit_definition_id": str(row.member_visit_id),
                "depends_on_visit_definition_id": str(row.cycle_visit_id),
            }
            for row in membership
        ]
        bind.execute(
            text(
                "INSERT INTO visit_definition_dependencies ("
                "id, visit_definition_id, depends_on_visit_definition_id, "
                "dependency_type, condition_expression, created_at) "
                "VALUES (:id, :visit_definition_id, "
                ":depends_on_visit_definition_id, 'cycle_member', NULL, now())"
            ),
            rows,
        )

    # 7. Repoint cycle-referencing SoA entries onto the migrated visit row.
    op.execute(_REPOINT_SOA)

    # 8. Drop the now-redundant SoA cycle column + index.
    for ddl in _DROP_SOA_CYCLE_COLUMN:
        op.execute(ddl)

    # 9. Drop the deprecated cycle tables (children first).
    for ddl in _DROP_CYCLE_TABLES:
        op.execute(ddl)

    # 10. Raw-data label/suffix columns.
    op.execute(_ADD_RAW_DATA_COLUMNS)

    # 11. CRF blinding columns.
    op.execute(_ADD_CRF_COLUMNS)


# ---------------------------------------------------------------------------
# downgrade() ordered DDL (reverse, best-effort value-preserving)
# ---------------------------------------------------------------------------

_DROP_CRF_COLUMNS = """
    ALTER TABLE crf_access_definitions
        DROP COLUMN unblind_role,
        DROP COLUMN blinded
"""

_DROP_RAW_DATA_COLUMNS = """
    ALTER TABLE raw_data_variable_settings
        DROP COLUMN suffix,
        DROP COLUMN label
"""

_RECREATE_CYCLE_TABLES = [
    """
    CREATE TABLE cycle_definitions (
        id UUID NOT NULL,
        study_version_id UUID NOT NULL,
        name VARCHAR(100) NOT NULL,
        display_order INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT uq_cycle_definition_name_per_version UNIQUE (study_version_id, name),
        FOREIGN KEY(study_version_id) REFERENCES study_versions (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_cycle_definitions_study_version_id ON cycle_definitions (study_version_id)",
    """
    CREATE TABLE cycle_definition_visits (
        cycle_definition_id UUID NOT NULL,
        visit_definition_id UUID NOT NULL,
        PRIMARY KEY (cycle_definition_id, visit_definition_id),
        FOREIGN KEY(cycle_definition_id) REFERENCES cycle_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY(visit_definition_id) REFERENCES visit_definitions (id) ON DELETE CASCADE
    )
    """,
]

# Rebuild cycle_definitions from the migrated visit rows (id preserved so it
# round-trips). visit_number / is_required are discarded (caveat d).
_REBUILD_CYCLE_DEFINITIONS = """
    INSERT INTO cycle_definitions (id, study_version_id, name, display_order, created_at)
    SELECT id, study_version_id, name, display_order, created_at
    FROM visit_definitions
    WHERE visit_type = 'cycle'
"""

# Rebuild membership from the 'cycle_member' dependency edges.
_REBUILD_CYCLE_MEMBERSHIP = """
    INSERT INTO cycle_definition_visits (cycle_definition_id, visit_definition_id)
    SELECT depends_on_visit_definition_id, visit_definition_id
    FROM visit_definition_dependencies
    WHERE dependency_type = 'cycle_member'
"""

_READD_SOA_CYCLE_COLUMN = [
    "ALTER TABLE schedule_of_assessment_entries ADD COLUMN cycle_definition_id UUID NULL",
    """
    ALTER TABLE schedule_of_assessment_entries
        ADD CONSTRAINT fk_soa_entries_cycle_definition_id
        FOREIGN KEY (cycle_definition_id) REFERENCES cycle_definitions (id) ON DELETE CASCADE
    """,
    "CREATE INDEX ix_schedule_of_assessment_entries_cycle_definition_id ON schedule_of_assessment_entries (cycle_definition_id)",
]

# Restore the original SoA split: entries pointing at a cycle-visit move back
# into cycle_definition_id with visit_definition_id nulled (caveat e).
_RESTORE_SOA_SPLIT = [
    """
    UPDATE schedule_of_assessment_entries
       SET cycle_definition_id = visit_definition_id
     WHERE visit_definition_id IN (SELECT id FROM cycle_definitions)
    """,
    """
    UPDATE schedule_of_assessment_entries
       SET visit_definition_id = NULL
     WHERE visit_definition_id IN (SELECT id FROM cycle_definitions)
    """,
]

_REMOVE_MIGRATED_CYCLE_ARTIFACTS = [
    "DELETE FROM visit_definition_dependencies WHERE dependency_type = 'cycle_member'",
    "DELETE FROM visit_definitions WHERE visit_type = 'cycle'",
]

_DROP_NEW_TABLES = [
    "DROP TABLE IF EXISTS visit_definition_dependencies CASCADE",
    "DROP TABLE IF EXISTS form_definition_dependencies CASCADE",
    "DROP TABLE IF EXISTS arm_definition_visits CASCADE",
]

_REVERT_VISIT_COLUMNS = [
    "DROP INDEX IF EXISTS ix_visit_definitions_visit_type",
    """
    ALTER TABLE visit_definitions
        DROP COLUMN cycle_length,
        DROP COLUMN repeat_max,
        DROP COLUMN repeat_min
    """,
    "ALTER TABLE visit_definitions ALTER COLUMN visit_type DROP DEFAULT",
]


def downgrade() -> None:
    # 1. CRF columns.
    op.execute(_DROP_CRF_COLUMNS)

    # 2. Raw-data columns.
    op.execute(_DROP_RAW_DATA_COLUMNS)

    # 3. Recreate the cycle tables (0051 DDL).
    for ddl in _RECREATE_CYCLE_TABLES:
        op.execute(ddl)

    # 4. Rebuild cycle_definitions from migrated visit rows (id preserved).
    op.execute(_REBUILD_CYCLE_DEFINITIONS)

    # 5. Rebuild membership from 'cycle_member' dependency edges.
    op.execute(_REBUILD_CYCLE_MEMBERSHIP)

    # 6. Re-add the SoA cycle column + FK + index, then restore the split.
    for ddl in _READD_SOA_CYCLE_COLUMN:
        op.execute(ddl)
    for ddl in _RESTORE_SOA_SPLIT:
        op.execute(ddl)

    # 7. Remove the migrated cycle rows and their 'cycle_member' edges.
    for ddl in _REMOVE_MIGRATED_CYCLE_ARTIFACTS:
        op.execute(ddl)

    # 8. Drop the new association + dependency tables.
    for ddl in _DROP_NEW_TABLES:
        op.execute(ddl)

    # 9. Revert the visit_definitions additive columns + discriminator index.
    for ddl in _REVERT_VISIT_COLUMNS:
        op.execute(ddl)
