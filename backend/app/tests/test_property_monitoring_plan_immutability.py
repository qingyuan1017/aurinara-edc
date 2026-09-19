"""Property coverage for immutable CTMS monitoring-plan versions.

The test uses the real ``MonitoringService`` with a deterministic in-memory
session and bookkeeping fakes.  No database or external service is required;
the fake models the repository boundary's append-only guards for published
versions and schedule history.

**Validates: Requirements 6.1-6.4, 6.13, 12.1-12.5, 14.5**

Property 7: Published monitoring plans are immutable and amend by version.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.monitoring import (
    MonitoringActivityScheduleHistory,
    MonitoringPlan,
    MonitoringPlanStatus,
    MonitoringPlanVersion,
    MonitoringPlanVersionStatus,
)
from app.models.site import Site
from app.models.study import Study
from app.services.ctms_atomicity_service import ctms_atomicity_service
from app.services.monitoring_service import MonitoringService


@dataclass(frozen=True)
class FakeAudit:
    entity_type: str
    entity_id: UUID
    action: str
    actor_id: UUID
    reason: str | None
    correlation_id: str


@dataclass(frozen=True)
class FakeOutbox:
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    correlation_id: str


@dataclass(frozen=True)
class FakeHistory:
    entity_type: str
    entity_id: UUID
    status: str
    reason: str | None
    correlation_id: str


class _FakeScalarResult:
    def __init__(self, records: list[Any]):
        self.records = records

    def all(self) -> list[Any]:
        return list(self.records)


class _FakeResult:
    def __init__(self, records: list[Any]):
        self.records = records

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self.records)


@dataclass
class InMemoryMonitoringState:
    """Deterministic repository and append-only bookkeeping fake."""

    study: Study
    site: Site
    records: list[Any] = field(default_factory=list)
    histories: list[FakeHistory] = field(default_factory=list)
    audits: list[FakeAudit] = field(default_factory=list)
    outbox: list[FakeOutbox] = field(default_factory=list)
    schedule_history: list[MonitoringActivityScheduleHistory] = field(default_factory=list)
    _version_snapshots: dict[UUID, tuple[Any, ...]] = field(default_factory=dict)

    def add(self, record: Any) -> None:
        if getattr(record, "id", None) is None:
            record.id = uuid4()
        self.records.append(record)
        if isinstance(record, MonitoringPlanVersion):
            self._version_snapshots[record.id] = self._version_snapshot(record)

    async def flush(self) -> None:
        # The fake captures the allowed Draft -> Published transition just as
        # the ORM/database immutability guard does after a successful flush.
        for record in self.records:
            if not isinstance(record, MonitoringPlanVersion):
                continue
            previous = self._version_snapshots.get(record.id)
            if (
                previous is not None
                and previous[2] == MonitoringPlanVersionStatus.DRAFT.value
                and record.status == MonitoringPlanVersionStatus.PUBLISHED.value
            ):
                self._version_snapshots[record.id] = self._version_snapshot(record)
        return None

    async def execute(self, statement: Any) -> _FakeResult:
        """Resolve only entities queried by MonitoringService and identity resolution."""

        entity = statement.column_descriptions[0]["entity"]
        if entity is Study:
            return _FakeResult([self.study])
        if entity is Site:
            return _FakeResult([self.site])
        if entity is MonitoringPlan:
            return _FakeResult(
                [
                    record
                    for record in self.records
                    if isinstance(record, MonitoringPlan)
                    and record.deleted_at is None
                ]
            )
        if entity is MonitoringPlanVersion:
            return _FakeResult(
                [record for record in self.records if isinstance(record, MonitoringPlanVersion)]
            )
        return _FakeResult([])

    @staticmethod
    def _version_snapshot(version: MonitoringPlanVersion) -> tuple[Any, ...]:
        return (
            version.plan_id,
            version.version_number,
            version.status,
            version.objectives,
            tuple(version.activity_types or []),
            version.frequency,
            version.frequency_value,
            version.frequency_unit,
            version.cadence,
            deepcopy(version.responsibilities),
            deepcopy(version.scope),
            version.completion_criteria,
            version.risk_level,
            version.risk_strategy,
            version.monitoring_strategy,
            version.risk_threshold,
            deepcopy(version.thresholds),
            version.amendment_reason,
            version.published_by,
            version.published_at,
        )

    def bookkeeping_snapshot(self) -> tuple[int, int, int, int]:
        return (
            len(self.histories),
            len(self.audits),
            len(self.outbox),
            len(self.schedule_history),
        )

    def reject_version_mutation(self, version: MonitoringPlanVersion, field: str, value: Any) -> None:
        """Apply the repository's published-row guard without changing state."""

        if version.status == MonitoringPlanVersionStatus.PUBLISHED.value:
            raise ValueError("Published monitoring plan versions are immutable")
        setattr(version, field, value)

    def reject_version_delete(self, version: MonitoringPlanVersion) -> None:
        if version.status == MonitoringPlanVersionStatus.PUBLISHED.value:
            raise ValueError("Published monitoring plan versions are immutable")
        self.records.remove(version)

    def reject_schedule_history_mutation(
        self, history: MonitoringActivityScheduleHistory, reason: str
    ) -> None:
        del history, reason
        raise ValueError("Monitoring activity schedule history is immutable")


async def _record_mutation(session: InMemoryMonitoringState, **kwargs: object) -> None:
    entity_id = kwargs["entity_id"]
    actor_id = kwargs.get("actor_id")
    correlation_id = str(kwargs["correlation_id"])
    assert isinstance(entity_id, UUID)
    assert isinstance(actor_id, UUID)

    status = kwargs.get("status")
    if status is not None:
        session.histories.append(
            FakeHistory(
                entity_type=str(kwargs["entity_type"]),
                entity_id=entity_id,
                status=str(status),
                reason=(str(kwargs["reason"]) if kwargs.get("reason") is not None else None),
                correlation_id=correlation_id,
            )
        )
    session.audits.append(
        FakeAudit(
            entity_type=str(kwargs["entity_type"]),
            entity_id=entity_id,
            action=str(kwargs["action"]),
            actor_id=actor_id,
            reason=(str(kwargs["reason"]) if kwargs.get("reason") is not None else None),
            correlation_id=correlation_id,
        )
    )
    session.outbox.append(
        FakeOutbox(
            aggregate_type=str(kwargs["entity_type"]),
            aggregate_id=entity_id,
            event_type=str(kwargs.get("event_type") or kwargs["action"]),
            correlation_id=correlation_id,
        )
    )
    await session.flush()


def _state() -> tuple[InMemoryMonitoringState, UUID]:
    actor_id = uuid4()
    study = Study(id=uuid4(), study_code=f"MON-{uuid4().hex[:8]}", title="Monitoring study")
    site = Site(id=uuid4(), study_id=study.id, site_number="001", name="Monitoring site")
    return InMemoryMonitoringState(study=study, site=site), actor_id


@st.composite
def plan_case(draw: st.DrawFn) -> dict[str, Any]:
    text = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=1, max_size=24)
    reason = st.one_of(
        st.sampled_from(["", " ", "\t"]),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=1, max_size=24),
    )
    return {
        "version_state": draw(st.sampled_from(["Draft", "Published", "Retired"])),
        "amendment_reason": draw(reason),
        "actor_marker": draw(text),
        "correlation": draw(st.from_regex(r"corr-[a-z0-9]{1,12}", fullmatch=True)),
        "cadence": draw(text),
        "objectives": draw(text),
        "attempted_cadence": draw(text),
    }


def _atomicity_fake():
    return patch.object(ctms_atomicity_service, "record_mutation", _record_mutation)


@given(case=plan_case())
@settings(max_examples=100, deadline=None, derandomize=True)
@pytest.mark.asyncio
async def test_published_monitoring_plan_versions_are_immutable_and_traceable(
    case: dict[str, Any],
) -> None:
    """Published plans amend by append-only versioning and reject side effects."""

    state, actor_id = _state()
    service = MonitoringService()
    with _atomicity_fake():
        plan = await service.create_plan(
            state,
            study_id=state.study.id,
            site_id=state.site.id,
            actor_id=actor_id,
            correlation_id=case["correlation"],
            payload={
                "name": f"Plan {case['actor_marker']}",
                "objectives": case["objectives"],
                "activity_types": ["Routine Monitoring"],
                "cadence": case["cadence"],
            },
        )
        draft = next(
            version
            for version in state.records
            if isinstance(version, MonitoringPlanVersion)
            and version.plan_id == plan.id
        )
        published = await service.publish_plan(
            state,
            plan,
            version=draft,
            actor_id=actor_id,
            correlation_id=case["correlation"],
        )
        assert published.status == MonitoringPlanVersionStatus.PUBLISHED.value
        assert plan.status == MonitoringPlanStatus.PUBLISHED.value
        assert plan.current_version_id == published.id

        published_snapshot = state._version_snapshot(published)
        pointer_before = plan.current_version_id
        side_effects_before_rejections = state.bookkeeping_snapshot()

        with pytest.raises(ConflictError, match="immutable"):
            await service.update_plan(
                state,
                plan,
                {"name": "Rejected direct published edit"},
                actor_id=actor_id,
                correlation_id=case["correlation"],
            )
        assert state.bookkeeping_snapshot() == side_effects_before_rejections
        assert plan.current_version_id == pointer_before
        assert state._version_snapshot(published) == published_snapshot

        with pytest.raises(ValidationError, match="amendment reason"):
            await service.amend_plan(
                state,
                plan,
                {"cadence": case["attempted_cadence"]},
                reason="   ",
                actor_id=actor_id,
                correlation_id=case["correlation"],
            )
        assert state.bookkeeping_snapshot() == side_effects_before_rejections
        assert plan.current_version_id == pointer_before

        with pytest.raises(ValueError, match="immutable"):
            state.reject_version_mutation(published, "cadence", case["attempted_cadence"])
        with pytest.raises(ValueError, match="immutable"):
            state.reject_version_delete(published)
        assert state.bookkeeping_snapshot() == side_effects_before_rejections
        assert state._version_snapshot(published) == published_snapshot
        assert plan.current_version_id == pointer_before

        amendment_reason = case["amendment_reason"].strip()
        if amendment_reason:
            before_versions = [
                version
                for version in state.records
                if isinstance(version, MonitoringPlanVersion)
            ]
            before_amendment = state.bookkeeping_snapshot()
            amended = await service.amend_plan(
                state,
                plan,
                {"cadence": case["cadence"]},
                reason=case["amendment_reason"],
                actor_id=actor_id,
                correlation_id=case["correlation"],
            )
            assert amended.status == MonitoringPlanVersionStatus.DRAFT.value
            assert amended.version_number == published.version_number + 1
            assert amended.amendment_reason == amendment_reason
            assert len(
                [
                    version
                    for version in state.records
                    if isinstance(version, MonitoringPlanVersion)
                ]
            ) == len(before_versions) + 1
            assert plan.current_version_id == pointer_before
            assert state._version_snapshot(published) == published_snapshot
            assert state.bookkeeping_snapshot() == (
                before_amendment[0] + 1,
                before_amendment[1] + 1,
                before_amendment[2] + 1,
                before_amendment[3],
            )
            assert state.audits[-1].actor_id == actor_id
            assert state.audits[-1].reason == amendment_reason
            assert state.audits[-1].correlation_id == case["correlation"]
            assert state.outbox[-1].correlation_id == case["correlation"]

            if case["version_state"] == MonitoringPlanVersionStatus.RETIRED.value:
                amended.status = MonitoringPlanVersionStatus.RETIRED.value
                assert amended.status == MonitoringPlanVersionStatus.RETIRED.value
                assert plan.current_version_id == pointer_before

        history = MonitoringActivityScheduleHistory(
            id=uuid4(),
            activity_id=uuid4(),
            planned_date=published.created_at,
            reason="Initial schedule",
            changed_by=actor_id,
            correlation_id=case["correlation"],
        )
        state.schedule_history.append(history)
        history_before = (
            history.activity_id,
            history.planned_date,
            history.reason,
            history.changed_by,
            history.correlation_id,
        )
        bookkeeping_before_history_rejection = state.bookkeeping_snapshot()
        with pytest.raises(ValueError, match="immutable"):
            state.reject_schedule_history_mutation(history, "Unauthorized history edit")
        assert (
            history.activity_id,
            history.planned_date,
            history.reason,
            history.changed_by,
            history.correlation_id,
        ) == history_before
        assert state.bookkeeping_snapshot() == bookkeeping_before_history_rejection
        assert plan.current_version_id == pointer_before
        assert state._version_snapshots[published.id] == published_snapshot
        assert all(a.correlation_id for a in state.audits)
        assert all(item.correlation_id for item in state.outbox)
