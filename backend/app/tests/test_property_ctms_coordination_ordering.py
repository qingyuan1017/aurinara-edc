"""Property 12: coordination preserves source order and projection freshness.

# Feature: ctms-integration, Property 12: Coordination preserves source order and freshness

**Validates: Requirements 8.11-8.12, 9.8-9.9, 9.17-9.18**

The property exercises the production projection service with deterministic
in-memory persistence. It models one source record receiving a permutation of
versioned events, then checks both the stable ordering contract and the
freshness guard that prevents an older event from overwriting the current row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ctms import Module
from app.models.ctms.ownership import ProjectionType
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.ctms_projection_service import CTMSProjectionService


@dataclass(frozen=True)
class VersionedEvent:
    """One source snapshot for the same correlated entity."""

    source_sequence: int
    source_version: str
    status: str
    source_timestamp: datetime
    event_id: str

    @property
    def payload(self) -> dict[str, str]:
        return {"status": self.status, "source_version": self.source_version}

    def as_mapping(self, source_record_id: UUID) -> dict[str, Any]:
        return {
            "source_module": Module.EDC.value,
            "entity_type": "Subject",
            "source_record_id": str(source_record_id),
            "source_sequence": self.source_sequence,
            "source_version": self.source_version,
            "event_id": self.event_id,
        }


class _Session:
    """Minimal session implementing the methods used by the projection service."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


class _ProjectionRepository:
    """Deterministic in-memory repository with the production repository contract."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, UUID], CTMSOperationalProjection] = {}

    async def get(
        self,
        session: _Session,
        *,
        projection_type: str,
        source_module: str,
        source_record_id: UUID,
    ) -> CTMSOperationalProjection | None:
        return self.rows.get((projection_type, source_module, source_record_id))

    async def add(self, session: _Session, projection: CTMSOperationalProjection) -> CTMSOperationalProjection:
        session.add(projection)
        await session.flush()
        self.rows[(projection.projection_type, projection.source_module, projection.source_record_id)] = projection
        return projection


def _rule() -> StatusOwnershipRuleCreate:
    return StatusOwnershipRuleCreate(
        entity_type="Subject",
        field_path="status",
        authoritative_module=Module.EDC,
        writable_module=Module.EDC,
        projection_target=Module.CTMS,
        projection_type=ProjectionType.SUBJECT_STATUS,
        typed_allowlist={
            "status": ProjectionFieldType.STRING,
            "source_version": ProjectionFieldType.STRING,
        },
        version=1,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


@st.composite
def versioned_event_sets(draw: st.DrawFn) -> tuple[UUID, list[VersionedEvent]]:
    """Generate unique source versions and a delivery permutation for one entity."""

    sequences = draw(
        st.lists(
            st.integers(min_value=1, max_value=50),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )
    ordered_sequences = sorted(sequences)
    statuses = draw(
        st.lists(
            st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=20),
            min_size=len(ordered_sequences),
            max_size=len(ordered_sequences),
        )
    )
    base_timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    events = [
        VersionedEvent(
            source_sequence=sequence,
            source_version=str(sequence),
            status=status,
            source_timestamp=base_timestamp + timedelta(seconds=sequence),
            event_id=f"event-{index}",
        )
        for index, (sequence, status) in enumerate(zip(ordered_sequences, statuses, strict=True))
    ]
    return draw(st.uuids(version=4)), draw(st.permutations(events))


@given(case=versioned_event_sets())
@settings(max_examples=100, deadline=None, derandomize=True)
@pytest.mark.asyncio
async def test_coordination_preserves_source_order_and_projection_freshness(
    case: tuple[UUID, list[VersionedEvent]],
) -> None:
    """Every delivery permutation converges to the newest source snapshot."""

    source_record_id, delivery = case
    service = CTMSProjectionService
    rule = _rule()

    # The coordination ordering key is independent of delivery order and
    # returns the source sequence/version order for this one entity.
    ordered = service.order_events(
        [event.as_mapping(source_record_id) for event in delivery]
    )
    assert [event["source_sequence"] for event in ordered] == sorted(
        event.source_sequence for event in delivery
    )
    assert [event["source_version"] for event in ordered] == [
        event.source_version for event in sorted(delivery, key=lambda item: item.source_sequence)
    ]

    repository = _ProjectionRepository()
    projection_service = service(repository=repository)
    session = _Session()
    results = []
    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        for event in delivery:
            result = await projection_service.apply_projection(
                session,
                rule=rule,
                source_module=Module.EDC,
                source_record_id=source_record_id,
                payload=event.payload,
                source_version=event.source_version,
                source_sequence=event.source_sequence,
                source_timestamp=event.source_timestamp,
                correlation_id=f"property-12-{event.event_id}",
            )
            results.append((event, result))

    newest = max(delivery, key=lambda event: event.source_sequence)
    current = results[-1][1].projection
    assert len(repository.rows) == 1
    assert current.status is ProjectionStatus.CURRENT
    assert current.source_sequence == newest.source_sequence
    assert current.source_version == newest.source_version
    assert current.payload_json == newest.payload

    # Any event delivered after a newer sequence is rejected as stale and
    # reports the retained current version. Events that are not stale apply
    # normally; this makes the assertion independent of the chosen permutation.
    highest_seen = -1
    for event, result in results:
        if event.source_sequence < highest_seen:
            assert result.stale is True
            assert result.conflict is True
            assert result.applied is False
            assert result.current_version == str(highest_seen)
            assert result.reason == "OUT_OF_ORDER_EVENT"
        else:
            assert result.applied is True
            assert result.current_version == event.source_version
            highest_seen = event.source_sequence

    # A source snapshot that is already current is skipped while retaining the
    # same current version and projection identity.
    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        repeated = await projection_service.apply_projection(
            session,
            rule=rule,
            source_module=Module.EDC,
            source_record_id=source_record_id,
            payload=newest.payload,
            source_version=newest.source_version,
            source_sequence=newest.source_sequence,
            source_timestamp=newest.source_timestamp,
            correlation_id="property-12-repeat",
        )

    assert repeated.skipped is True
    assert repeated.applied is False
    assert repeated.current_version == newest.source_version
    assert repeated.projection.id == current.id
    assert repeated.projection.source_sequence == newest.source_sequence
