"""Focused tests for typed CTMS projection persistence and boundaries."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.ctms import Module
from app.core.exceptions import ConflictError
from app.models.ctms.ownership import ProjectionType
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.schemas.ctms.ownership import ProjectionFieldType, StatusOwnershipRuleCreate
from app.services.ctms_projection_service import CTMSProjectionService


class _Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


class _Repository:
    def __init__(self):
        self.rows = {}

    async def get(self, session, *, projection_type, source_module, source_record_id):
        return self.rows.get((projection_type, source_module, source_record_id))

    async def add(self, session, projection):
        session.add(projection)
        await session.flush()
        self.rows[(projection.projection_type, projection.source_module, projection.source_record_id)] = projection
        return projection

    async def get_by_id(self, session, projection_id):
        return next((row for row in self.rows.values() if row.id == projection_id), None)

    async def list(self, session, **filters):
        return list(self.rows.values())


def _rule():
    return StatusOwnershipRuleCreate(
        entity_type="Subject",
        field_path="status",
        authoritative_module=Module.EDC,
        writable_module=Module.EDC,
        projection_target=Module.CTMS,
        projection_type=ProjectionType.SUBJECT_STATUS,
        typed_allowlist={
            "subject_id": ProjectionFieldType.UUID,
            "status": ProjectionFieldType.STRING,
            "source_version": ProjectionFieldType.STRING,
        },
        version=2,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_apply_projection_persists_typed_metadata_and_only_allowlisted_payload():
    repository = _Repository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()
    subject_id = uuid4()
    source_id = uuid4()

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        result = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            subject_id=subject_id,
            payload={"subject_id": subject_id, "status": "Enrolled", "source_version": "7"},
            source_version="7",
            source_timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            correlation_id="corr-projection-1",
        )

    row = result.projection
    assert result.applied is True
    assert row.source_module == "EDC"
    assert row.source_record_id == source_id
    assert row.subject_id == subject_id
    assert row.rule_version == 2
    assert row.correlation_id == "corr-projection-1"
    assert row.status is ProjectionStatus.CURRENT
    assert row.payload_json == {
        "subject_id": str(subject_id),
        "status": "Enrolled",
        "source_version": "7",
    }
    assert len(row.payload_fingerprint) == 64
    assert row.read_only is True


@pytest.mark.asyncio
async def test_prohibited_projection_is_rejected_without_retaining_values():
    repository = _Repository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        result = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=uuid4(),
            payload={"status": "Enrolled", "clinical_data": {"value": "secret"}},
            source_version="1",
            source_timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            correlation_id="corr-rejected",
        )

    assert result.rejected is True
    assert result.projection.status is ProjectionStatus.REJECTED
    assert result.projection.payload_json == {}
    assert result.projection.rejected_fields_fingerprint is not None
    assert "secret" not in repr(result.projection)
    assert "secret" not in str(result.projection.payload_json)


@pytest.mark.asyncio
async def test_older_source_version_and_timestamp_cannot_overwrite_current_projection():
    repository = _Repository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()
    source_id = uuid4()
    base = datetime(2025, 1, 2, tzinfo=UTC)

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        current = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Enrolled", "source_version": "7"},
            source_version="7",
            source_timestamp=base,
            correlation_id="corr-current",
        )
        stale = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Screening", "source_version": "6"},
            source_version="6",
            source_timestamp=base - timedelta(minutes=1),
            correlation_id="corr-stale",
        )

    assert current.projection is stale.projection
    assert stale.stale is True
    assert stale.applied is False
    assert stale.projection.payload_json["status"] == "Enrolled"
    assert stale.projection.source_version == "7"


def test_consumer_cannot_use_projection_as_clinical_write_authority():
    projection = CTMSOperationalProjection(
        projection_type=ProjectionType.SUBJECT_STATUS.value,
        source_module=Module.EDC.value,
        source_record_id=uuid4(),
        source_version="1",
        source_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        rule_version=1,
        correlation_id="corr-read-only",
        payload_json={"status": "Enrolled"},
        payload_fingerprint="f" * 64,
    )
    assert CTMSProjectionService.consumer_can_mutate_source(
        projection=projection, operation="projected_subject_update"
    ) is False
    with pytest.raises(ConflictError) as error:
        CTMSProjectionService.assert_consumer_read_only("update_clinical_data")
    assert error.value.details["reason"] == "PROJECTION_READ_ONLY"



def test_source_events_are_ordered_by_entity_sequence_and_version_deterministically():
    source_id = uuid4()
    events = [
        {"aggregate_type": "subject", "aggregate_id": source_id, "source_sequence": 3, "source_version": "3", "event_id": "b"},
        {"aggregate_type": "subject", "aggregate_id": source_id, "source_sequence": 1, "source_version": "1", "event_id": "a"},
        {"aggregate_type": "subject", "aggregate_id": source_id, "source_sequence": 2, "source_version": "2", "event_id": "c"},
    ]

    ordered = CTMSProjectionService.order_events(events)

    assert [event["source_sequence"] for event in ordered] == [1, 2, 3]


@pytest.mark.asyncio
async def test_current_projection_is_skipped_and_records_current_version():
    repository = _Repository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()
    source_id = uuid4()
    timestamp = datetime(2025, 1, 2, tzinfo=UTC)

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Enrolled", "source_version": "7"},
            source_version="7",
            source_sequence=7,
            source_timestamp=timestamp,
            correlation_id="corr-current-1",
        )
        result = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Enrolled", "source_version": "7"},
            source_version="7",
            source_sequence=7,
            source_timestamp=timestamp,
            correlation_id="corr-current-2",
        )

    assert result.skipped is True
    assert result.outcome == "skipped"
    assert result.current_version == "7"
    assert result.projection.source_sequence == 7


@pytest.mark.asyncio
async def test_out_of_order_sequence_conflicts_without_overwriting_newer_projection():
    repository = _Repository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()
    source_id = uuid4()
    timestamp = datetime(2025, 1, 2, tzinfo=UTC)

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        current = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Enrolled", "source_version": "7"},
            source_version="7",
            source_sequence=7,
            source_timestamp=timestamp,
            correlation_id="corr-sequence-current",
        )
        stale = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Screening", "source_version": "6"},
            source_version="6",
            source_sequence=6,
            source_timestamp=timestamp + timedelta(days=1),
            correlation_id="corr-sequence-stale",
        )

    assert stale.conflict is True
    assert stale.reason == "OUT_OF_ORDER_EVENT"
    assert stale.current_version == "7"
    assert stale.projection is current.projection
    assert stale.projection.payload_json["status"] == "Enrolled"
    assert stale.projection.source_sequence == 7


@pytest.mark.asyncio
async def test_refresh_preserves_target_scope_and_rebuild_metadata_when_omitted():
    repository = _Repository()
    service = CTMSProjectionService(repository=repository)
    session = _Session()
    source_id = uuid4()
    study_id = uuid4()
    generation = uuid4()
    timestamp = datetime(2025, 1, 2, tzinfo=UTC)

    with patch("app.services.ctms_projection_service.audit_service.record", new=AsyncMock()):
        await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            study_id=study_id,
            payload={"status": "Screening", "source_version": "1"},
            source_version="1",
            source_sequence=1,
            source_timestamp=timestamp,
            rebuild_generation=generation,
            correlation_id="corr-refresh-1",
        )
        refreshed = await service.apply_projection(
            session,
            rule=_rule(),
            source_module=Module.EDC,
            source_record_id=source_id,
            payload={"status": "Enrolled", "source_version": "2"},
            source_version="2",
            source_sequence=2,
            source_timestamp=timestamp + timedelta(minutes=1),
            correlation_id="corr-refresh-2",
        )

    assert refreshed.applied is True
    assert refreshed.projection.source_version == "2"
    assert refreshed.projection.source_sequence == 2
    assert refreshed.projection.study_id == study_id
    assert refreshed.projection.rebuild_generation == generation
