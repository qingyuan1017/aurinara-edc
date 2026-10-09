"""create designer tables (phases, cycles, arms, SoA, CRF access, raw-data vars, coding settings)

The Designer / EDC refactor introduced new design-time tables owned by the
Designer module, but no migration created them (migrations 0048-0050 only added
the ``design_version_id`` binding columns to operational tables). This migration
creates the nine missing Designer tables so the Designer authoring surfaces
(subject phases, cycles, arms, schedule of assessment, CRF access, raw-data
variable settings, coding settings) can read and write.

``visit_definitions`` already exists (it predates the refactor) and is NOT
recreated here; the new tables reference it and ``study_versions`` /
``form_definitions`` / ``field_definitions`` by foreign key.

The DDL mirrors the SQLAlchemy models exactly (emitted via the PostgreSQL
dialect). It is additive only — no existing table or column is altered.

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | None = None
depends_on: str | None = None


# Parent tables (reference study_versions / form_definitions / field_definitions /
# visit_definitions, all of which already exist). Created before the association
# and child tables that depend on them.
_PARENT_TABLES_DDL = [
    """
    CREATE TABLE subject_phase_definitions (
        id UUID NOT NULL,
        design_version_id UUID NOT NULL,
        name VARCHAR(100) NOT NULL,
        display_order INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT uq_subject_phase_definition_name_per_version UNIQUE (design_version_id, name),
        FOREIGN KEY(design_version_id) REFERENCES study_versions (id) ON DELETE CASCADE
    )
    """,
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
    """
    CREATE TABLE arm_definitions (
        id UUID NOT NULL,
        study_version_id UUID NOT NULL,
        name VARCHAR(100) NOT NULL,
        display_order INTEGER NOT NULL,
        description TEXT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT uq_arm_definition_name_per_version UNIQUE (study_version_id, name),
        FOREIGN KEY(study_version_id) REFERENCES study_versions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE raw_data_variable_settings (
        id UUID NOT NULL,
        design_version_id UUID NOT NULL,
        name VARCHAR(255) NOT NULL,
        data_type VARCHAR(50) NOT NULL,
        attributes JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(design_version_id) REFERENCES study_versions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE coding_settings (
        id UUID NOT NULL,
        design_version_id UUID NOT NULL,
        field_definition_id UUID,
        dictionary_reference VARCHAR(255) NOT NULL,
        coding_rule TEXT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(design_version_id) REFERENCES study_versions (id) ON DELETE CASCADE,
        FOREIGN KEY(field_definition_id) REFERENCES field_definitions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE crf_access_definitions (
        id UUID NOT NULL,
        design_version_id UUID NOT NULL,
        role VARCHAR(100) NOT NULL,
        form_definition_id UUID,
        field_definition_id UUID,
        can_read BOOLEAN NOT NULL,
        can_write BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(design_version_id) REFERENCES study_versions (id) ON DELETE CASCADE,
        FOREIGN KEY(form_definition_id) REFERENCES form_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY(field_definition_id) REFERENCES field_definitions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE schedule_of_assessment (
        id UUID NOT NULL,
        design_version_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(design_version_id) REFERENCES study_versions (id) ON DELETE CASCADE
    )
    """,
]

# Association + child tables (depend on the parents above and on existing
# visit_definitions / form_definitions).
_DEPENDENT_TABLES_DDL = [
    """
    CREATE TABLE cycle_definition_visits (
        cycle_definition_id UUID NOT NULL,
        visit_definition_id UUID NOT NULL,
        PRIMARY KEY (cycle_definition_id, visit_definition_id),
        FOREIGN KEY(cycle_definition_id) REFERENCES cycle_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY(visit_definition_id) REFERENCES visit_definitions (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE schedule_of_assessment_entries (
        id UUID NOT NULL,
        schedule_of_assessment_id UUID NOT NULL,
        form_definition_id UUID,
        procedure_name VARCHAR(255),
        visit_definition_id UUID,
        cycle_definition_id UUID,
        display_order INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(schedule_of_assessment_id) REFERENCES schedule_of_assessment (id) ON DELETE CASCADE,
        FOREIGN KEY(form_definition_id) REFERENCES form_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY(visit_definition_id) REFERENCES visit_definitions (id) ON DELETE CASCADE,
        FOREIGN KEY(cycle_definition_id) REFERENCES cycle_definitions (id) ON DELETE CASCADE
    )
    """,
]

_INDEXES_DDL = [
    "CREATE INDEX ix_subject_phase_definitions_design_version_id ON subject_phase_definitions (design_version_id)",
    "CREATE INDEX ix_cycle_definitions_study_version_id ON cycle_definitions (study_version_id)",
    "CREATE INDEX ix_arm_definitions_study_version_id ON arm_definitions (study_version_id)",
    "CREATE INDEX ix_raw_data_variable_settings_design_version_id ON raw_data_variable_settings (design_version_id)",
    "CREATE INDEX ix_coding_settings_design_version_id ON coding_settings (design_version_id)",
    "CREATE INDEX ix_coding_settings_field_definition_id ON coding_settings (field_definition_id)",
    "CREATE INDEX ix_crf_access_definitions_design_version_id ON crf_access_definitions (design_version_id)",
    "CREATE INDEX ix_crf_access_definitions_form_definition_id ON crf_access_definitions (form_definition_id)",
    "CREATE INDEX ix_crf_access_definitions_field_definition_id ON crf_access_definitions (field_definition_id)",
    "CREATE INDEX ix_schedule_of_assessment_design_version_id ON schedule_of_assessment (design_version_id)",
    "CREATE INDEX ix_schedule_of_assessment_entries_schedule_id ON schedule_of_assessment_entries (schedule_of_assessment_id)",
    "CREATE INDEX ix_schedule_of_assessment_entries_form_definition_id ON schedule_of_assessment_entries (form_definition_id)",
    "CREATE INDEX ix_schedule_of_assessment_entries_visit_definition_id ON schedule_of_assessment_entries (visit_definition_id)",
    "CREATE INDEX ix_schedule_of_assessment_entries_cycle_definition_id ON schedule_of_assessment_entries (cycle_definition_id)",
]

# Drop order is the reverse of creation (children/associations before parents).
_DROP_ORDER = [
    "schedule_of_assessment_entries",
    "cycle_definition_visits",
    "schedule_of_assessment",
    "crf_access_definitions",
    "coding_settings",
    "raw_data_variable_settings",
    "arm_definitions",
    "cycle_definitions",
    "subject_phase_definitions",
]


def upgrade() -> None:
    for ddl in _PARENT_TABLES_DDL:
        op.execute(ddl)
    for ddl in _DEPENDENT_TABLES_DDL:
        op.execute(ddl)
    for ddl in _INDEXES_DDL:
        op.execute(ddl)


def downgrade() -> None:
    for table in _DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
