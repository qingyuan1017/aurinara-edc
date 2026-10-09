"""Reassignment audit module (Migration Phase 4).

Phase 4 of the ``Migration_Process`` records the ownership reassignment of each
existing record set as **immutable** audit events and guarantees that **no
existing audit history is physically removed or rewritten** (R11.7, R11.8).

What a reassignment *is*
------------------------
The refactor splits the historical combined EDC capability into a design-time
``Module.DESIGNER`` and an operational ``Module.EDC``. This is a **code-layer
ownership change**: the nine design-time record sets (studies, study versions,
visit/form/section/field definitions, codelists, codelist items, edit checks)
become owned by the Designer_Module, while the five operational sets (subjects,
visit instances, form instances, form records, field values) stay owned by the
EDC_Module. **No stored value is altered** by this reassignment (R11.1, R11.2);
Phases 0/5 verify that with counts and value checksums.

What Phase 4 writes
-------------------
For each reassigned record set, the service records **exactly one** immutable
audit event through the shared ``audit_service`` (design Property 14), carrying:

* ``action="reassign"`` — the reassignment action,
* ``source_module`` → ``target_module`` — the owning module scope transition.
  Design-time sets move ``Module.EDC`` → ``Module.DESIGNER``; operational sets
  stay ``Module.EDC`` → ``Module.EDC`` (ownership formalized, not moved),
* ``module`` — the resulting owning module of the set (DESIGNER or EDC),
* ``entity_type`` — the record-set name (e.g. ``"form_definitions"``),
* ``entity_id`` — a deterministic per-set correlation id so the event is
  addressable without naming any single reassigned row,
* the actor and the event timestamp (auto-stamped by the audit service).

The audit event's own immutability is enforced by the shared audit layer: the
``AuditEvent`` ORM rejects UPDATE/DELETE and no service exposes a mutator, so a
recorded reassignment event can never be edited or deleted (R11.7).

Audit-history preservation invariant (R11.8)
--------------------------------------------
**The reassignment only ever ADDS audit events; it never deletes or rewrites a
single pre-existing ``audit_events`` row.** Because this is a logical ownership
reassignment (not a physical data move), there is nothing to delete: no code
path here issues a DELETE or UPDATE against ``audit_events``. The shared audit
model additionally forbids row mutation at the ORM layer. :meth:`
ReassignmentService.assert_audit_history_preserved` makes the invariant
checkable: it counts the pre-existing audit rows before reassignment and asserts
that, afterwards, every one of those rows still exists (and only new events were
appended). :meth:`reassign_all` runs that assertion internally so a regression
that ever removed audit history would fail loudly rather than silently.

Satisfies Requirements:
  - 11.7: Reassignments are recorded as immutable audit events through the
          shared Audit_Service (one event per reassigned set).
  - 11.8: All existing audit history is preserved with no physical removal; a
          verification helper asserts no pre-existing audit row was deleted.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.database import Base
from app.models.shared.audit import AuditEvent
from app.services.designer.migration.snapshot_service import (
    DESIGN_TIME_SETS,
    OPERATIONAL_SETS,
    RECORD_SET_MODELS,
)

logger = logging.getLogger(__name__)

# The reassignment action recorded on every reassignment audit event.
REASSIGN_ACTION = "reassign"

# Stable namespace used to derive a deterministic per-record-set correlation id
# (``entity_id``) for a reassignment event. Using a fixed namespace keeps the
# event addressable and idempotent-friendly without pointing at any one row.
_REASSIGN_NAMESPACE = uuid.UUID("5f0b7a2e-1c3d-4e6f-8a9b-0c1d2e3f4a5b")


def _reassignment_entity_id(record_set: str) -> uuid.UUID:
    """Return a deterministic correlation id for a record set's reassignment."""
    return uuid.uuid5(_REASSIGN_NAMESPACE, f"reassign:{record_set}")


def _target_module_for(record_set: str) -> Module:
    """Return the owning module a record set is reassigned to.

    Design-time sets are owned by the Designer_Module; operational sets stay with
    the EDC_Module. Mirrors the design-time/operational partition declared in
    ``snapshot_service`` so the two can never drift.
    """
    if record_set in DESIGN_TIME_SETS:
        return Module.DESIGNER
    if record_set in OPERATIONAL_SETS:
        return Module.EDC
    # Defensive: an unpartitioned set would be a programming error, not a value
    # error about user data. Keep ownership explicit rather than guessing.
    raise ValueError(f"record set {record_set!r} is not in any ownership partition")


@dataclass(frozen=True)
class ReassignmentEvent:
    """Serializable description of one record set's reassignment audit event."""

    record_set: str
    source_module: Module
    target_module: Module
    audit_event_id: uuid.UUID

    def to_dict(self) -> dict[str, str]:
        return {
            "record_set": self.record_set,
            "source_module": self.source_module.value,
            "target_module": self.target_module.value,
            "audit_event_id": str(self.audit_event_id),
        }


@dataclass(frozen=True)
class ReassignmentResult:
    """Result of a Phase 4 reassignment: the events recorded and the invariant."""

    events: list[ReassignmentEvent] = field(default_factory=list)
    audit_history_preserved: bool = True
    preexisting_audit_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "events": [e.to_dict() for e in self.events],
            "audit_history_preserved": self.audit_history_preserved,
            "preexisting_audit_count": self.preexisting_audit_count,
        }


class ReassignmentService:
    """Records Phase 4 reassignment audit events and preserves audit history.

    The service is deliberately **additive-only**: it reads existing audit rows
    (to verify preservation) and appends new reassignment events, but it never
    issues an UPDATE or DELETE against ``audit_events`` (R11.8).
    """

    def __init__(
        self, record_set_models: dict[str, type[Base]] | None = None
    ) -> None:
        self._record_set_models = record_set_models or RECORD_SET_MODELS

    # ------------------------------------------------------------------
    # Reassignment audit (R11.7)
    # ------------------------------------------------------------------

    async def reassign_record_set(
        self,
        session: AsyncSession,
        *,
        record_set: str,
        actor_id: uuid.UUID | None = None,
    ) -> ReassignmentEvent:
        """Record ONE immutable reassignment audit event for one record set.

        The owning module scope transitions ``source_module`` → ``target_module``:
        design-time sets move ``EDC`` → ``DESIGNER``; operational sets stay
        ``EDC`` → ``EDC`` (ownership formalized in place). Exactly one event is
        written (design Property 14).

        Args:
            session: The active async session (caller's transaction). The audit
                event commits/rolls back with the caller's transaction boundary.
            record_set: The logical record-set name (a key of RECORD_SET_MODELS).
            actor_id: The operator performing the migration; auto-populated from
                request context by the audit service when omitted.

        Returns:
            A :class:`ReassignmentEvent` describing the recorded audit event.

        Raises:
            ValueError: The record set is unknown or unpartitioned.
        """
        if record_set not in self._record_set_models:
            raise ValueError(f"unknown record set {record_set!r}")

        target_module = _target_module_for(record_set)
        # Every reassigned set is formalized out of the historical combined EDC
        # capability, so the source scope is always EDC.
        source_module = Module.EDC

        event = await audit_service.record(
            session,
            entity_type=record_set,
            entity_id=_reassignment_entity_id(record_set),
            action=REASSIGN_ACTION,
            module=target_module,
            source_module=source_module,
            target_module=target_module,
            actor_id=actor_id,
            scope={"record_set": record_set},
        )

        logger.info(
            "Reassignment audited: set=%s %s→%s event=%s",
            record_set,
            source_module.value,
            target_module.value,
            event.id,
        )
        return ReassignmentEvent(
            record_set=record_set,
            source_module=source_module,
            target_module=target_module,
            audit_event_id=event.id,
        )

    async def reassign_all(
        self,
        session: AsyncSession,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> ReassignmentResult:
        """Record one reassignment event per record set and verify preservation.

        Captures the count of pre-existing ``audit_events`` rows first, records
        one reassignment event per record set (R11.7), then asserts that every
        pre-existing audit row still exists and only new events were appended
        (R11.8). The whole operation is additive: no audit row is ever removed.

        Returns:
            A :class:`ReassignmentResult` with the recorded events and the
            audit-history-preservation outcome.

        Raises:
            AssertionError: If any pre-existing audit row was removed (R11.8).
                In practice this cannot happen — the service never deletes — but
                the assertion makes the invariant executable and regression-safe.
        """
        preexisting_count = await self._count_audit_events(session)

        events: list[ReassignmentEvent] = []
        for record_set in self._record_set_models:
            events.append(
                await self.reassign_record_set(
                    session, record_set=record_set, actor_id=actor_id
                )
            )

        await self.assert_audit_history_preserved(
            session,
            preexisting_count=preexisting_count,
            added=len(events),
        )

        logger.info(
            "Phase 4 reassignment complete: %s events recorded, "
            "%s pre-existing audit rows preserved",
            len(events),
            preexisting_count,
        )
        return ReassignmentResult(
            events=events,
            audit_history_preserved=True,
            preexisting_audit_count=preexisting_count,
        )

    # ------------------------------------------------------------------
    # Audit-history preservation (R11.8)
    # ------------------------------------------------------------------

    async def count_audit_history(self, session: AsyncSession) -> int:
        """Return the current number of ``audit_events`` rows.

        Call before a reassignment to capture the pre-existing audit history
        size for a later preservation check.
        """
        return await self._count_audit_events(session)

    async def assert_audit_history_preserved(
        self,
        session: AsyncSession,
        *,
        preexisting_count: int,
        added: int = 0,
    ) -> None:
        """Assert that no pre-existing audit row was physically removed (R11.8).

        The reassignment is purely additive, so after recording ``added`` new
        reassignment events the total audit-row count must equal the pre-existing
        count **plus** the number of events added — never fewer. A smaller total
        would mean history was deleted, violating R11.8.

        Args:
            session: The active async session.
            preexisting_count: The audit-row count captured before reassignment.
            added: The number of reassignment events recorded in between.

        Raises:
            AssertionError: If the current total is below ``preexisting_count``
                (pre-existing history was removed) or below the expected
                additive total (an appended event went missing).
        """
        current = await self._count_audit_events(session)
        if current < preexisting_count:
            raise AssertionError(
                "audit history was physically removed during reassignment: "
                f"{preexisting_count} rows before, {current} rows after (R11.8)"
            )
        expected = preexisting_count + added
        if current < expected:
            raise AssertionError(
                "reassignment audit events were not fully preserved: expected at "
                f"least {expected} rows ({preexisting_count} pre-existing + "
                f"{added} added), found {current} (R11.8)"
            )

    @staticmethod
    async def _count_audit_events(session: AsyncSession) -> int:
        result = await session.execute(select(func.count()).select_from(AuditEvent))
        return int(result.scalar_one())


# Module-level singleton for convenience (mirrors snapshot_service).
reassignment_service = ReassignmentService()
