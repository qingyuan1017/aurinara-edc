"""Add phase-gated PV read-only EDC adverse-event projection tables.

Feature: pv-safety-module, Task 5.1

This revision is additive. It creates ``pv_edc_ae_projections`` and
``pv_coordination_refs``, the PV-side read model for the approved, minimized,
read-only ``Safety_Operational_Projection`` of EDC adverse events consumed
through the shared ``Coordination_Service`` transactional outbox, plus the
coordination references that keep projected EDC records traceable by correlation
identifier (Requirement 17.6).

Design ("Coordination and read-only projection consumption"): EDC appends an
approved projection event containing only the fields designated for PV release
(subject reference, verbatim term, onset date, seriousness) plus the source
identifier, rule version, correlation identifier, and processing outcome. A PV
worker upserts the projection idempotently by ``Idempotency_Key``; a stale event
never overwrites a current projection; an unapproved/unauthorized projection
request is recorded as ``Rejected`` and delivers no content (Requirements 10.4,
23.6, 23.7, 23.8). The projection is read-only for PV; nothing here opens a write
path into EDC clinical or CTMS operational state (Requirement 23.10).

Both tables use a UUID primary key, UTC ``TIMESTAMPTZ`` columns, actor/
correlation metadata, and retention/soft-deletion columns. Partial indexes
exclude soft-deleted rows and deduplicate live rows by idempotency key. These
tables are read-model projections rather than PV Safety_Data, so they are not
gated by the PV Safety_Data physical-deletion guard.

The optional PostgreSQL setting ``app.pv_phase`` is a deployment gate. When set
it must be at least 2 (EDC adverse-event reconciliation and the projection are a
Phase 2 capability); an unset setting preserves local/offline migration
compatibility while allowing production provisioning to gate the revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_TABLES = (
    "pv_edc_ae_projections",
    "pv_coordination_refs",
)

_PROJECTION_STATUS_VALUES = ("Current", "Stale", "Rejected")
_PROJECTION_STATUS_SQL = "','".join(_PROJECTION_STATUS_VALUES)

_NOT_DELETED = sa.text("deleted_at IS NULL")


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled at least PV Phase 2."""

    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                DO $$
                DECLARE configured_phase text;
                BEGIN
                    configured_phase := current_setting('app.pv_phase', true);
                    IF configured_phase IS NOT NULL
                       AND configured_phase <> ''
                       AND configured_phase::integer < 2 THEN
                        RAISE EXCEPTION
                            'PV projection migration is disabled by app.pv_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_pv_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating projections without the PV case root."""

    if (
        bind.dialect.name == "postgresql"
        and not context.is_offline_mode()
        and not inspect(bind).has_table("pv_safety_cases")
    ):
        raise RuntimeError(
            "PV projection tables require the pv_safety_cases table from revision 0038"
        )


def _common_metadata_columns() -> list[sa.Column]:
    """Return the shared PV metadata columns used by every projection table."""

    return [
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_pv_dependencies(bind)

    op.create_table(
        "pv_edc_ae_projections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_module", sa.String(20), nullable=False, server_default="EDC"),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("projection_status", sa.String(20), nullable=False, server_default="Current"),
        sa.Column("study_id", sa.Uuid()),
        sa.Column("site_id", sa.Uuid()),
        sa.Column("subject_reference", sa.Uuid()),
        sa.Column("verbatim_term", sa.String(200)),
        sa.Column("onset_date", sa.Date()),
        sa.Column("seriousness", sa.String(30)),
        sa.Column("rejection_reason", sa.String(160)),
        *_common_metadata_columns(),
        sa.CheckConstraint(
            f"projection_status IN ('{_PROJECTION_STATUS_SQL}')",
            name="ck_pv_edc_ae_projections_status",
        ),
        sa.CheckConstraint(
            "verbatim_term IS NULL OR length(verbatim_term) BETWEEN 1 AND 200",
            name="ck_pv_edc_ae_projections_verbatim_length",
        ),
    )
    op.create_index(
        "uq_pv_edc_ae_projections_idempotency",
        "pv_edc_ae_projections",
        ["idempotency_key"],
        unique=True,
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_edc_ae_projections_source",
        "pv_edc_ae_projections",
        ["source_module", "source_record_id"],
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_edc_ae_projections_scope_status",
        "pv_edc_ae_projections",
        ["study_id", "site_id", "projection_status"],
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_edc_ae_projections_correlation",
        "pv_edc_ae_projections",
        ["correlation_id"],
        postgresql_where=_NOT_DELETED,
    )

    op.create_table(
        "pv_coordination_refs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False, server_default="EDC"),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.String(128)),
        sa.Column("rule_version", sa.Integer()),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64)),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("sanitized_reason", sa.String(160)),
        sa.Column(
            "projection_id",
            sa.Uuid(),
            sa.ForeignKey("pv_edc_ae_projections.id", ondelete="SET NULL"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        *_common_metadata_columns(),
    )
    op.create_index(
        "uq_pv_coordination_refs_idempotency",
        "pv_coordination_refs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_coordination_refs_correlation",
        "pv_coordination_refs",
        ["correlation_id"],
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_coordination_refs_source",
        "pv_coordination_refs",
        ["source_module", "source_record_id"],
        postgresql_where=_NOT_DELETED,
    )


def downgrade() -> None:
    """Drop only PV projection objects, leaving other tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _PROJECTION_TABLES if name not in existing]
        if missing:
            raise RuntimeError(
                "Cannot downgrade PV projection tables; missing: " + ", ".join(missing)
            )

    for table in reversed(_PROJECTION_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
