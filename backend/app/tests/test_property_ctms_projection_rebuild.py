"""Property test for source-preserving, repeatable CTMS projection rebuilds.

**Validates: Requirements 8.1-8.7, 9.17, 14.6**

Property 15: Projection rebuilds are source-preserving and repeatable.

The property drives the real ``ProjectionRebuildWorker`` with deterministic
source, projection, and rebuild-state repositories.  Generated source records
represent either EDC or CTMS authority and retain independent status and audit
history snapshots.  Rebuilds may update only the CTMS read model and rebuild
metadata; the authoritative source snapshots must remain unchanged.
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
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.ctms_projection_service import CTMSProjectionService
from app.workers.projection_rebuild_worker import (
    AuthoritativeRecordSnapshot,
    ProjectionRebuildWorker,
)


@dataclass(frozen=True, slots=True)
class AuthoritativeRecord:
    """Immutable source state exposed to the deterministic reader."""

    source_record_id: UUID
    source_module: Module
    source_version: str
    source_timestamp: datetime
    study_id: UUID
    site_id: UUID
    subject_id: UUID
    approved_reference: str
    status: str
    audit_history: tuple[tuple[str, str], ...]

    def snapshot(self) -> tuple[Any, ...]:
        """Capture source fields, status, and audit history for comparison."""

        return (
            self.source_record_id,
            self.source_module,
            self.source_version,
            self.source_timestamp,
            self.study_id,
            self.site_id,
            self.subject_id,
            self.approved_reference,
            self.status,
            self.audit_history,
        )

    def to_projection_source(self) -> AuthoritativeRecordSnapshot:
        """Return the allowlisted source view consumed by the rebuild worker."""

        return AuthoritativeRecordSnapshot(
            source_record_id=self.source_record_id,
            source_module=self.source_module,
            source_version=self.source_version,
            source_timestamp=self.source_timestamp,
            study_id=self.study_id,
            site_id=self.site_id,
            subject_id=self.subject_id,
            payload={
                "subject_id": self.subject_id,
                "approved_reference": self.approved_reference,
                "status": self.status,
                "source_version": self.source_version,
            },
        )


class _Session:
    """Minimal async session fake used by the deterministic repositories."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


class _ProjectionRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, UUID], Any] = {}

    async def get(
        self, session: _Session, *, projection_type: str, source_module: str, source_record_id: UUID
    ):
        return self.rows.get((projection_type, source_module, source_record_id))

    async def add(self, session: _Session, projection: Any) -> Any:
        session.add(projection)
        await session.flush()
        self.rows[
            (projection.projection_type, projection.source_module, projection.source_record_id)
        ] = projection
        return projection


class _StateRepository:
    def __init__(self) -> None:
        self.states: list[Any] = []

    async def add(self, session: _Session, state: Any) -> Any:
        session.add(state)
        await session.flush()
        self.states.append(state)
        return state


class _Reader:
    def __init__(self, records: tuple[AuthoritativeRecord, ...]) -> None:
        self.records = records

    async def list_records(
        self, session: _Session, **kwargs: Any
    ) -> list[AuthoritativeRecordSnapshot]:
        # Deliberately return the source rows in reverse order.  The worker must
        # use stable canonical ordering and must not rely on reader ordering.
        return [record.to_projection_source() for record in reversed(self.records)]


def _rule(version: int) -> StatusOwnershipRuleCreate:
    return StatusOwnershipRuleCreate(
        entity_type="Subject",
        field_path="status",
        authoritative_module=Module.EDC,
        writable_module=Module.EDC,
        projection_target=Module.CTMS,
        projection_type=ProjectionType.SUBJECT_STATUS,
        typed_allowlist={
            "subject_id": ProjectionFieldType.UUID,
            "approved_reference": ProjectionFieldType.STRING,
            "status": ProjectionFieldType.STRING,
            "source_version": ProjectionFieldType.STRING,
        },
        version=version,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


@st.composite
def _scenario(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a scoped authoritative source set and active rule generation."""

    count = draw(st.integers(min_value=1, max_value=5))
    study_id = draw(st.uuids(version=4))
    site_id = draw(st.uuids(version=4))
    source_module = draw(st.sampled_from((Module.EDC, Module.CTMS)))
    source_ids = draw(st.lists(st.uuids(version=4), min_size=count, max_size=count, unique=True))
    subject_ids = draw(st.lists(st.uuids(version=4), min_size=count, max_size=count, unique=True))
    versions = draw(
        st.lists(
            st.integers(min_value=1, max_value=100).map(str),
            min_size=count,
            max_size=count,
        )
    )
    statuses = draw(
        st.lists(
            st.sampled_from(("Screening", "Enrolled", "Completed", "Withdrawn")),
            min_size=count,
            max_size=count,
        )
    )
    references = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
                min_size=1,
                max_size=16,
            ),
            min_size=count,
            max_size=count,
        )
    )
    audit_histories = draw(
        st.lists(
            st.lists(
                st.tuples(
                    st.sampled_from(("create", "status_change", "review")),
                    st.text(
                        alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
                        min_size=1,
                        max_size=12,
                    ),
                ),
                max_size=3,
            ),
            min_size=count,
            max_size=count,
        )
    )
    rule_version = draw(st.integers(min_value=1, max_value=50))

    records = tuple(
        AuthoritativeRecord(
            source_record_id=source_ids[index],
            source_module=source_module,
            source_version=versions[index],
            source_timestamp=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=index),
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_ids[index],
            approved_reference=references[index],
            status=statuses[index],
            audit_history=tuple(audit_histories[index]),
        )
        for index in range(count)
    )
    return {
        "study_id": study_id,
        "site_id": site_id,
        "source_module": source_module,
        "records": records,
        "rule_version": rule_version,
    }


def _projection_signature(rows: tuple[Any, ...]) -> dict[UUID, tuple[Any, ...]]:
    """Compare rebuild output while intentionally excluding generation metadata."""

    return {
        row.source_record_id: (
            row.projection_type,
            row.source_module,
            row.source_version,
            row.source_timestamp,
            row.rule_version,
            row.status,
            row.payload_json,
            row.payload_fingerprint,
        )
        for row in rows
    }


@settings(max_examples=100, deadline=None)
@given(scenario=_scenario())
@pytest.mark.asyncio
async def test_projection_rebuilds_are_source_preserving_and_repeatable(
    scenario: dict[str, Any],
) -> None:
    """Repeated rebuilds reproduce the same read model without source mutation.

    **Validates: Requirements 8.1-8.7, 9.17, 14.6**
    """

    records: tuple[AuthoritativeRecord, ...] = scenario["records"]
    source_before = tuple(record.snapshot() for record in records)
    repository = _ProjectionRepository()
    state_repository = _StateRepository()
    worker = ProjectionRebuildWorker(
        source_reader=_Reader(records),
        projection_service=CTMSProjectionService(repository=repository),
        state_repository=state_repository,
    )

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        first = await worker.rebuild(
            _Session(),
            study_id=scenario["study_id"],
            site_id=scenario["site_id"],
            projection_type=ProjectionType.SUBJECT_STATUS,
            source_module=scenario["source_module"],
            rule=_rule(scenario["rule_version"]),
            generation=uuid4(),
            correlation_id="property-rebuild-first",
        )
        first_signature = _projection_signature(first.projections)
        source_after_first = tuple(record.snapshot() for record in records)

        second = await worker.rebuild(
            _Session(),
            study_id=scenario["study_id"],
            site_id=scenario["site_id"],
            projection_type=ProjectionType.SUBJECT_STATUS,
            source_module=scenario["source_module"],
            rule=_rule(scenario["rule_version"]),
            generation=uuid4(),
            correlation_id="property-rebuild-second",
        )
        second_signature = _projection_signature(second.projections)
        source_after_second = tuple(record.snapshot() for record in records)

    assert first.state.status.value == "completed"
    assert second.state.status.value == "completed"
    assert first.state.rule_version == scenario["rule_version"]
    assert second.state.rule_version == scenario["rule_version"]
    assert first_signature == second_signature
    assert len(repository.rows) == len(records)
    assert all(row.read_only for row in second.projections)

    # Rebuilds read source state but never change authoritative records,
    # including their status and immutable audit history, for either module.
    assert source_after_first == source_before
    assert source_after_second == source_before
    assert tuple(record.status for record in records) == tuple(
        snapshot[8] for snapshot in source_before
    )
    assert tuple(record.audit_history for record in records) == tuple(
        snapshot[9] for snapshot in source_before
    )
