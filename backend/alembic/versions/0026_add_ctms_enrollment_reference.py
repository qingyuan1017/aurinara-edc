"""Add the approved operational subject reference field.

The field is an optional CTMS display/reference value.  The canonical
``subject_id`` remains the EDC-owned identity and is not replaced or copied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ctms_operational_milestones",
        sa.Column("approved_reference", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ctms_operational_milestones", "approved_reference")
