"""Add ODM 2.0 Designer identities and metadata.

Revision ID: 0073
Revises: 0072
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,254}$")


def _oid(prefix: str, value: object) -> str:
    return f"{prefix}.{uuid.UUID(str(value)).hex.upper()}"


def _add_and_backfill(table_name: str, column_name: str, prefix: str) -> None:
    op.add_column(table_name, sa.Column(column_name, sa.String(255), nullable=True))
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET {column_name} = "
            f"'{prefix}.' || upper(replace(CAST(id AS VARCHAR), '-', ''))"
        )
    )
    op.alter_column(table_name, column_name, nullable=False)


def _seed_permissions() -> None:
    bind = op.get_bind()
    permissions = (
        ("designer.odm.import", "Validate and import ODM 2.0 Designer metadata"),
        ("designer.odm.export", "Export ODM 2.0 Designer metadata"),
    )
    if context.is_offline_mode():
        for code, description in permissions:
            op.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, description) "
                    "VALUES (gen_random_uuid(), :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code, description=description)
            )
            op.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = :code "
                    "WHERE r.name = 'Designer_Role' AND NOT EXISTS ("
                    "SELECT 1 FROM role_permissions rp "
                    "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
                ).bindparams(code=code)
            )
        return
    for code, description in permissions:
        if bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, description) "
                    "VALUES (gen_random_uuid(), :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code, description=description)
            )
        else:
            exists = bind.execute(
                sa.text("SELECT id FROM permissions WHERE code = :code").bindparams(code=code)
            ).first()
            if exists is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO permissions (id, code, description) "
                        "VALUES (:id, :code, :description)"
                    ).bindparams(id=str(uuid.uuid4()), code=code, description=description)
                )
        op.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = :code "
                "WHERE r.name = 'Designer_Role' AND NOT EXISTS ("
                "SELECT 1 FROM role_permissions rp "
                "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
            ).bindparams(code=code)
        )


def upgrade() -> None:
    _add_and_backfill("study_versions", "odm_study_oid", "STUDY")
    _add_and_backfill("study_versions", "odm_metadata_version_oid", "MDV")
    _add_and_backfill("visit_definitions", "odm_oid", "SE")
    _add_and_backfill("form_definitions", "odm_oid", "FORM")
    _add_and_backfill("form_sections", "odm_oid", "IG")
    _add_and_backfill("field_definitions", "odm_oid", "ITEM")
    _add_and_backfill("codelists", "odm_oid", "CL")
    _add_and_backfill("edit_checks", "odm_oid", "COND")

    # Preserve a valid legacy field ODM ID when one was explicitly authored.
    bind = op.get_bind()
    if context.is_offline_mode() or bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE field_definitions SET odm_oid = odm_id "
                "WHERE odm_id ~ '^[A-Za-z][A-Za-z0-9_.-]{0,254}$'"
            )
        )

    op.create_index("ix_visit_definitions_odm_oid", "visit_definitions", ["odm_oid"])
    op.create_index("ix_field_definitions_odm_oid", "field_definitions", ["odm_oid"])
    op.create_index("ix_codelists_odm_oid", "codelists", ["odm_oid"])
    op.create_index("ix_edit_checks_odm_oid", "edit_checks", ["odm_oid"])
    op.create_unique_constraint(
        "uq_study_version_odm_mdv_oid",
        "study_versions",
        ["study_id", "odm_metadata_version_oid"],
    )

    op.add_column(
        "form_sections", sa.Column("is_repeating", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("form_sections", sa.Column("repeat_min", sa.Integer(), nullable=True))
    op.add_column("form_sections", sa.Column("repeat_max", sa.Integer(), nullable=True))
    op.add_column(
        "codelist_items", sa.Column("specify", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    for name, type_ in (
        ("data_format", sa.String(100)),
        ("review_group", sa.String(255)),
        ("dynamic_search_config", sa.JSON()),
    ):
        op.add_column("field_definitions", sa.Column(name, type_, nullable=True))
    for name, default in (
        ("allows_partial_date", sa.false()),
        ("source_document", sa.true()),
        ("query_future_date", sa.false()),
        ("query_nonconformance", sa.false()),
        ("breaks_signature", sa.true()),
    ):
        op.add_column(
            "field_definitions",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=default),
        )
    op.add_column(
        "edit_checks", sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "edit_checks", sa.Column("needs_retesting", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("edit_checks", sa.Column("retesting_reason", sa.Text(), nullable=True))
    op.add_column("coding_settings", sa.Column("dictionary_version", sa.String(100), nullable=True))
    op.add_column("coding_settings", sa.Column("coding_level", sa.String(100), nullable=True))
    op.add_column("coding_settings", sa.Column("locale", sa.String(35), nullable=True))
    op.add_column("coding_settings", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("coding_settings", sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("coding_settings", sa.Column("auto_approval", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "measurement_unit_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_version_id", sa.Uuid(), sa.ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("odm_oid", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(100), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(), nullable=True),
        sa.Column("conversion_offset", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_measurement_units_version", "measurement_unit_definitions", ["study_version_id"])
    op.create_index("ix_measurement_units_oid", "measurement_unit_definitions", ["odm_oid"])
    op.create_table(
        "derivation_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_version_id", sa.Uuid(), sa.ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_field_definition_id", sa.Uuid(), sa.ForeignKey("field_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("odm_oid", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("expression_json", sa.JSON(), nullable=False),
        sa.Column("execution_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("needs_retesting", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retesting_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_derivations_version", "derivation_definitions", ["study_version_id"])
    op.create_index("ix_derivations_target", "derivation_definitions", ["target_field_definition_id"])
    op.create_index("ix_derivations_oid", "derivation_definitions", ["odm_oid"])
    _seed_permissions()


def downgrade() -> None:
    for code in ("designer.odm.import", "designer.odm.export"):
        op.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ).bindparams(code=code)
        )
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))
    op.drop_table("derivation_definitions")
    op.drop_table("measurement_unit_definitions")
    for column in (
        "auto_approval", "approval_required", "priority", "locale", "coding_level",
        "dictionary_version",
    ):
        op.drop_column("coding_settings", column)
    for column in ("retesting_reason", "needs_retesting", "schema_version"):
        op.drop_column("edit_checks", column)
    for column in (
        "breaks_signature", "query_nonconformance", "query_future_date", "source_document",
        "allows_partial_date", "dynamic_search_config", "review_group", "data_format",
    ):
        op.drop_column("field_definitions", column)
    op.drop_column("codelist_items", "specify")
    for column in ("repeat_max", "repeat_min", "is_repeating"):
        op.drop_column("form_sections", column)
    op.drop_constraint("uq_study_version_odm_mdv_oid", "study_versions", type_="unique")
    for table, index in (
        ("edit_checks", "ix_edit_checks_odm_oid"),
        ("codelists", "ix_codelists_odm_oid"),
        ("field_definitions", "ix_field_definitions_odm_oid"),
        ("visit_definitions", "ix_visit_definitions_odm_oid"),
    ):
        op.drop_index(index, table_name=table)
    for table in ("edit_checks", "codelists", "field_definitions", "form_sections", "form_definitions", "visit_definitions"):
        op.drop_column(table, "odm_oid")
    op.drop_column("study_versions", "odm_metadata_version_oid")
    op.drop_column("study_versions", "odm_study_oid")
