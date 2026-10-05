"""PV retention lifecycle ledger owned by the PV_Safety_Module.

The ``PVRetentionAction`` table is an immutable actor/time/reason ledger for
every PV retention lifecycle action (archive, soft-delete, restore). It supports
Requirement 17.2 (Soft_Deletion retains deletion actor, timestamp, and reason)
and Requirement 20.3 (retention/backup/restore controls) by making each PV
retention decision attributable and append-only.

PV retention is deliberately implemented as updates to PV-owned/shared metadata;
it never issues deletes against EDC clinical tables, CTMS operational tables, or
their attachments, and it never physically removes PV Safety_Data or a related
Audit_Event.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for the retention ledger."""

    return datetime.now(UTC)


class PVRetentionAction(Base):
    """Immutable actor/time/reason ledger for every PV retention lifecycle action."""

    __tablename__ = "pv_retention_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module: Mapped[str] = mapped_column(String(20), nullable=False, default="PV")

    __table_args__ = (
        Index("ix_pv_retention_actions_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_pv_retention_actions_action", "action", "occurred_at"),
    )


def _reject_retention_action_mutation(
    _mapper: Any, _connection: Any, _target: PVRetentionAction
) -> None:
    """PV retention history is append-only; updates and deletes are forbidden."""

    raise ValueError("PV retention action history is immutable")


event.listen(PVRetentionAction, "before_update", _reject_retention_action_mutation)
event.listen(PVRetentionAction, "before_delete", _reject_retention_action_mutation)


__all__ = ["PVRetentionAction"]
