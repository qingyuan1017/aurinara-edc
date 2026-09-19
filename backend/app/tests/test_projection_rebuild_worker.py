"""Deterministic, source-preserving projection rebuild coverage."""

from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.ctms import Module
from app.models.ctms.ownership import ProjectionType
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.ctms_projection_service import CTMSProjectionService
from app.workers.projection_rebuild_worker import (
    AuthoritativeRecordSnapshot,
    ProjectionRebuildWorker,
)


class _Session:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


class _ProjectionRepository:
    def __init__(self) -> None:
        self.rows = {}

    async def get(self, session, *, projection_type, source_module, source_record_id):
        return self.rows.get((projection_type, source_module, source_record_id))

    async def add(self, session, projection):
        session.add(projection)
        await session.flush()
        self.rows[(projection.projection_type, projection.source_module, projection.source_record_id)] = projection
        return projection


class _StateRepository:
    def __init__(self) -> None:
        self.states = []

    async def add(self, session, state):
        session.add(state)
        await session.flush()
        self.states.append(state)
        return state


class _Reader:
    def __init__(self, records) -> None:
        self.records = list(records)
        self.calls = []

    async def list_records(self, session, **kwargs):
        self.calls.append(kwargs)
        return list(reversed(self.records))


def _rule() -> StatusOwnershipRuleCreate:
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
        version=4,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _records(study_id, site_id):
    return [
        AuthoritativeRecordSnapshot(
            source_record_id=uuid4(),
            source_module=Module.EDC,
            source_version="2",
            source_timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid4(),
            payload={"subject_id": uuid4(), "approved_reference": "SUB-2", "status": "Enrolled", "source_version": "2"},
        ),
        AuthoritativeRecordSnapshot(
            source_record_id=uuid4(),
            source_module=Module.EDC,
            source_version="1",
            source_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            study_id=study_id,
            site_id=site_id,
            subject_id=uuid4(),
            payload={"subject_id": uuid4(), "approved_reference": "SUB-1", "status": "Screening", "source_version": "1"},
        ),
    ]


@pytest.mark.asyncio
async def test_rebuild_sorts_sources_and_records_generation_watermark():
    study_id, site_id = uuid4(), uuid4()
    records = _records(study_id, site_id)
    source_before = deepcopy(records)
    reader = _Reader(records)
    projection_repo = _ProjectionRepository()
    worker = ProjectionRebuildWorker(
        source_reader=reader,
        projection_service=CTMSProjectionService(repository=projection_repo),
        state_repository=_StateRepository(),
    )

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        result = await worker.rebuild(
            _Session(),
            study_id=study_id,
            site_id=site_id,
            projection_type=ProjectionType.SUBJECT_STATUS,
            source_module=Module.EDC,
            rule=_rule(),
            generation=uuid4(),
            correlation_id="rebuild-1",
        )

    assert [item.source_record_id for item in result.projections] == sorted(
        (item.source_record_id for item in records), key=str
    )
    assert result.state.status.value == "completed"
    assert result.state.records_seen == 2
    assert result.state.records_applied == 2
    assert result.state.watermark_version == "2"
    assert result.state.watermark_timestamp == datetime(2025, 1, 2, tzinfo=UTC)
    assert result.state.watermark_record_id == records[0].source_record_id
    assert records == source_before
    assert reader.calls[0]["study_id"] == study_id
    assert reader.calls[0]["site_id"] == site_id


@pytest.mark.asyncio
async def test_repeated_rebuilds_keep_typed_payloads_and_fingerprints_stable():
    study_id, site_id = uuid4(), uuid4()
    records = _records(study_id, site_id)
    reader = _Reader(records)
    projection_repo = _ProjectionRepository()
    state_repo = _StateRepository()

    worker = ProjectionRebuildWorker(
        source_reader=reader,
        projection_service=CTMSProjectionService(repository=projection_repo),
        state_repository=state_repo,
    )
    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        first = await worker.rebuild(
            _Session(), study_id=study_id, site_id=site_id,
            projection_type=ProjectionType.SUBJECT_STATUS, source_module=Module.EDC, rule=_rule(),
            generation=uuid4(), correlation_id="rebuild-1",
        )
        first_values = [(row.payload_json.copy(), row.payload_fingerprint) for row in first.projections]
        second = await worker.rebuild(
            _Session(), study_id=study_id, site_id=site_id,
            projection_type=ProjectionType.SUBJECT_STATUS, source_module=Module.EDC, rule=_rule(),
            generation=uuid4(), correlation_id="rebuild-2",
        )

    second_values = [(row.payload_json.copy(), row.payload_fingerprint) for row in second.projections]
    assert second_values == first_values
    assert first.state.generation != second.state.generation
    assert second.state.status.value == "completed"
    assert all(row.rebuild_generation == second.state.generation for row in second.projections)
    assert len(projection_repo.rows) == 2
    assert len(state_repo.states) == 2


@pytest.mark.asyncio
async def test_rebuild_is_limited_to_requested_scope_and_does_not_emit_outbox_work():
    study_id, site_id, other_site_id = uuid4(), uuid4(), uuid4()
    records = _records(study_id, site_id) + _records(study_id, other_site_id)
    reader = _Reader(records)
    projection_repo = _ProjectionRepository()
    session = _Session()

    worker = ProjectionRebuildWorker(
        source_reader=reader,
        projection_service=CTMSProjectionService(repository=projection_repo),
        state_repository=_StateRepository(),
    )
    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        result = await worker.rebuild(
            session, study_id=study_id, site_id=site_id,
            projection_type=ProjectionType.SUBJECT_STATUS, source_module=Module.EDC, rule=_rule(),
            generation=uuid4(), correlation_id="rebuild-scope",
        )

    assert result.state.scope_study_id == study_id
    assert result.state.scope_site_id == site_id
    assert all(row.site_id == site_id for row in result.projections)
    assert not any(item.__class__.__name__ == "CTMSOutbox" for item in session.added)
