"""Seed the additive PV/Safety authorization permission codes.

Feature: pv-safety-module, Task 1.4

Revision 0038 seeds the Phase 1 base PV permissions (``safety_case.enter``,
``safety_case.read``, ``safety_case.lifecycle``, ``safety_assessment.record``,
``safety_audit.read``). This revision is additive and seeds the remaining PV
authorization permission codes needed for the full safety workflow so the shared
``Permission_Service`` can resolve one ``Authorization_Scope`` for every PV
operation (Requirements 1.x, 2.x, 18.4):

  - ``safety_coding.assign``        MedDRA/WHODrug coding assignment
  - ``safety_narrative.write``      Case_Narrative create/revise
  - ``safety_report.manage``        Regulatory reporting and ICSR/E2B submission
  - ``safety_reconciliation.run``   One-way read-only EDC reconciliation
  - ``safety_export.create``        Safety export jobs

The seed is idempotent and touches only the shared ``permissions`` table; it
never creates a competing identity table and never grants an EDC clinical or
CTMS operational permission. PV roles are bound to these codes by the shared
runtime seeder in ``app/core/permissions.py``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Additive PV permission seeds (the five Phase 1 codes are seeded by 0038).
_PV_PERMISSIONS = (
    ("safety_coding.assign", "Assign MedDRA/WHODrug coding to PV safety terms"),
    ("safety_narrative.write", "Create and revise PV case narratives"),
    ("safety_report.manage", "Manage PV regulatory reporting and ICSR/E2B submissions"),
    ("safety_reconciliation.run", "Run one-way read-only EDC adverse-event reconciliation"),
    ("safety_export.create", "Create PV safety export jobs"),
)


def _seed_pv_permissions() -> None:
    """Insert PV permission codes idempotently; never touch EDC/CTMS permissions."""

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.Text()),
    )
    bind = op.get_bind()
    for code, description in _PV_PERMISSIONS:
        if bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, description) "
                    "VALUES (gen_random_uuid(), :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code, description=description)
            )
        else:
            existing = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).first()
            if existing is None:
                import uuid

                op.bulk_insert(
                    permissions,
                    [{"id": uuid.uuid4(), "code": code, "description": description}],
                )


def upgrade() -> None:
    _seed_pv_permissions()


def downgrade() -> None:
    """Remove the additive PV permission seeds without disturbing others."""

    for code, _ in _PV_PERMISSIONS:
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))
