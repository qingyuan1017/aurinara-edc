"""Property coverage for the CTMS operational study lifecycle.

**Validates: Requirements 3.1-3.10, 14.5-14.6**

Property 4: Operational study lifecycle is independent of clinical configuration.

The harness uses deterministic in-memory session, audit, and outbox fakes.  It
calls the real ``OperationalStudyService`` while avoiding a database and all
external services, so rejected commands can be checked for side-effect freedom
across the CTMS bookkeeping collections and the canonical EDC records.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.operational_study import (
    OperationalStudy,
    OperationalStudyStatus,
    StudyOperationalMilestone,
)
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.services.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms_ownership_guard import CTMSOwnershipError
from app.services.operational_study_service import OperationalStudyService

STUDY_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Planning"},
    "Planning": {"Ready", "Suspended"},
    "Ready": {"Active", "Planning", "Suspended"},
    "Active": {"Enrollment Closed", "Suspended", "Closed"},
    "Enrollment Closed": {"Suspended", "Closed"},
    "Suspended": {"Planning", "Ready", "Active", "Enrollment Closed", "Closed"},
    "Closed": set(),
}


@dataclass(frozen=True)
class FakeHistory:
    entity_type: str
    entity_id: UUID
    status: str
    previous_status: str | None
    reason: str | None
    correlation_id: str


@dataclass(frozen=True)
class FakeAudit:
    entity_type: str
    entity_id: UUID
    action: str
    reason: str | None
    correlation_id: str


@dataclass(frozen=True)
class FakeOutbox:
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    payload: dict[str, object]
    correlation_id: str


class _FakeScalarResult:
    def __init__(self, records: list[Any]):
        self.records = records

    def first(self) -> Any | None:
        return self.records[0] if self.records else None

    def all(self) -> list[Any]:
        return list(self.records)


class _FakeResult:
    def __init__(self, records: list[Any]):
        self.records = records

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self.records)


@dataclass
class InMemoryCTMSState:
    """A deterministic unit-of-work fake containing CTMS and canonical EDC state."""

    study: Study
    study_version: StudyVersion
    clinical_configuration: dict[str, object]
    added: list[Any] = field(default_factory=list)
    histories: list[FakeHistory] = field(default_factory=list)
    audits: list[FakeAudit] = field(default_factory=list)
    outbox: list[FakeOutbox] = field(default_factory=list)

    def snapshot_clinical(self) -> tuple[object, ...]:
        return (
            self.study.id,
            self.study.study_code,
            self.study.title,
            self.study.status,
            self.study_version.id,
            self.study_version.study_id,
            self.study_version.version_number,
            self.study_version.status,
            deepcopy(self.clinical_configuration),
        )

    def snapshot_bookkeeping(self) -> tuple[int, int, int]:
        return (len(self.histories), len(self.audits), len(self.outbox))

    def add(self, record: Any) -> None:
        if hasattr(record, "id") and record.id is None:
            record.id = uuid4()
        self.added.append(record)

    async def flush(self) -> None:
        return None

    async def execute(self, statement: Any) -> _FakeResult:
        """Resolve only the model types used by the real service and resolver."""

        entity = statement.column_descriptions[0]["entity"]
        if entity is Study:
            return _FakeResult([self.study])
        if entity is OperationalStudy:
            return _FakeResult(
                [
                    record
                    for record in self.added
                    if isinstance(record, OperationalStudy)
                    and record.study_id == self.study.id
                    and record.deleted_at is None
                ]
            )
        return _FakeResult([])


@dataclass(frozen=True)
class TransitionAttempt:
    target: str
    reason: str | None


@st.composite
def lifecycle_case(draw: st.DrawFn) -> dict[str, object]:
    """Generate lifecycle commands, reasons, canonical-reference choices, and payloads."""

    statuses = list(STUDY_TRANSITIONS)
    reasons = st.one_of(
        st.none(),
        st.sampled_from(["", " ", "\t"]),
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=1,
            max_size=14,
        ),
    )
    attempts = draw(
        st.lists(
            st.builds(
                TransitionAttempt,
                target=st.sampled_from(statuses),
                reason=reasons,
            ),
            min_size=1,
            max_size=8,
        )
    )
    return {
        "start_status": draw(st.sampled_from(statuses)),
        "attempts": attempts,
        "active_reason": draw(reasons),
        "archive_reason": draw(reasons),
        "archive_again": draw(st.booleans()),
        "canonical_reference_is_uuid": draw(st.booleans()),
        "clinical_field": draw(
            st.sampled_from(
                [
                    "study_version_id",
                    "clinical_configuration",
                    "protocol_visit_date",
                    "clinical_data",
                    "query_message",
                ]
            )
        ),
        "sponsor": draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=16)),
        "plan_title": draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=16)),
        "criterion_name": draw(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=16)
        ),
        "milestone_type": draw(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=16)
        ),
        "profile_marker": draw(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12)
        ),
    }


def _profile_snapshot(profile: OperationalStudy) -> tuple[object, ...]:
    return (
        profile.status,
        profile.retention_state,
        profile.archived_at,
        profile.archived_by,
        profile.retention_reason,
        profile.sponsor,
        profile.phase,
        profile.therapeutic_area,
        profile.indication,
        deepcopy(profile.planning_metadata),
        deepcopy(profile.readiness_criteria),
        profile.updated_by,
    )


def _build_state() -> tuple[InMemoryCTMSState, UUID]:
    actor_id = uuid4()
    study = Study(
        id=uuid4(),
        study_code=f"PBT-{uuid4()}",
        title="Canonical EDC study",
        status=StudyStatus.draft,
        created_by=actor_id,
    )
    version = StudyVersion(
        id=uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    return (
        InMemoryCTMSState(
            study=study,
            study_version=version,
            clinical_configuration={"protocol": "v1", "forms": ["screening"]},
        ),
        actor_id,
    )


def _atomicity_patch():
    async def record_mutation(session: InMemoryCTMSState, **kwargs: object) -> None:
        entity_id = kwargs["entity_id"]
        assert isinstance(entity_id, UUID)
        correlation_id = str(kwargs["correlation_id"])
        status = kwargs.get("status")
        if status is not None:
            session.histories.append(
                FakeHistory(
                    entity_type=str(kwargs["entity_type"]),
                    entity_id=entity_id,
                    status=str(status),
                    previous_status=(
                        str(kwargs["previous_status"])
                        if kwargs.get("previous_status") is not None
                        else None
                    ),
                    reason=(str(kwargs["reason"]) if kwargs.get("reason") is not None else None),
                    correlation_id=correlation_id,
                )
            )
        session.audits.append(
            FakeAudit(
                entity_type=str(kwargs["entity_type"]),
                entity_id=entity_id,
                action=str(kwargs["action"]),
                reason=(str(kwargs["reason"]) if kwargs.get("reason") is not None else None),
                correlation_id=correlation_id,
            )
        )
        payload = {
            key: value
            for key, value in (kwargs.get("payload") or {}).items()
            if isinstance(value, (str, int, float, bool, UUID)) or value is None
        }
        session.outbox.append(
            FakeOutbox(
                aggregate_type=str(kwargs["entity_type"]),
                aggregate_id=entity_id,
                event_type=str(kwargs.get("event_type") or kwargs["action"]),
                payload={
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in payload.items()
                },
                correlation_id=correlation_id,
            )
        )
        await session.flush()

    return patch.object(ctms_atomicity_service, "record_mutation", record_mutation)


def _with_atomicity_fake(function):
    @wraps(function)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _atomicity_patch():
            return await function(*args, **kwargs)

    return wrapper


@given(case=lifecycle_case())
@settings(max_examples=100, deadline=None, derandomize=True)
@_with_atomicity_fake
@pytest.mark.asyncio
async def test_operational_study_lifecycle_preserves_canonical_edc_state(
    case: dict[str, object],
) -> None:
    """Configured lifecycle commands mutate only CTMS and retain traceability."""

    state, actor_id = _build_state()
    session = state
    service = OperationalStudyService()
    clinical_before = state.snapshot_clinical()

    if not case["canonical_reference_is_uuid"]:
        with pytest.raises(ValidationError):
            await service.create_profile(
                session,
                study_id="EDC-STUDY-DISPLAY-NAME",
                actor_id=actor_id,
                payload={"sponsor": "Operations"},
            )
        assert session.added == []
        assert state.snapshot_bookkeeping() == (0, 0, 0)
        assert state.snapshot_clinical() == clinical_before
        return

    start_status = str(case["start_status"])
    profile = await service.create_profile(
        session,
        study_id=state.study.id,
        actor_id=actor_id,
        payload={
            "status": start_status,
            "sponsor": case["sponsor"],
            "phase": "Phase II",
            "therapeutic_area": "Oncology",
            "indication": "Operational indication",
            "planning_metadata": {"marker": case["profile_marker"]},
            "readiness_criteria": {"minimum_sites": 1},
        },
        correlation_id="profile-create",
    )
    assert profile.study_id == state.study.id
    assert profile.status == start_status

    plan = await service.create_study_plan(
        session,
        study_id=state.study.id,
        actor_id=actor_id,
        payload={"title": case["plan_title"], "objective": "Open sites"},
        correlation_id="plan-create",
    )
    enrollment_plan = await service.create_enrollment_plan(
        session,
        study_id=state.study.id,
        actor_id=actor_id,
        payload={"title": case["plan_title"], "target_quantity": 25},
        correlation_id="enrollment-plan-create",
    )
    criterion = await service.create_readiness_criterion(
        session,
        study_id=state.study.id,
        actor_id=actor_id,
        payload={"name": case["criterion_name"], "required": True},
        correlation_id="readiness-create",
    )
    milestone = await service.create_operational_milestone(
        session,
        study_id=state.study.id,
        actor_id=actor_id,
        payload={"title": case["plan_title"], "milestone_type": case["milestone_type"]},
        correlation_id="milestone-create",
    )
    assert (
        plan.study_id
        == enrollment_plan.study_id
        == criterion.study_id
        == milestone.study_id
        == state.study.id
    )
    assert isinstance(milestone, StudyOperationalMilestone)

    for attempt in case["attempts"]:
        assert isinstance(attempt, TransitionAttempt)
        before_profile = _profile_snapshot(profile)
        before_bookkeeping = state.snapshot_bookkeeping()
        current = str(profile.status)
        same_status = attempt.target == current
        legal = attempt.target in STUDY_TRANSITIONS[current]
        reason = attempt.reason.strip() if attempt.reason and attempt.reason.strip() else None
        if same_status:
            await service.transition_status(
                session,
                profile,
                attempt.target,
                reason=attempt.reason,
                actor_id=actor_id,
            )
            assert _profile_snapshot(profile) == before_profile
            assert state.snapshot_bookkeeping() == before_bookkeeping
        elif legal and reason is not None:
            await service.transition_status(
                session,
                profile,
                attempt.target,
                reason=attempt.reason,
                actor_id=actor_id,
                correlation_id=f"transition-{len(state.audits)}",
            )
            assert profile.status == attempt.target
            assert state.histories[-1].previous_status == current
            assert state.histories[-1].status == attempt.target
            assert state.histories[-1].reason == reason
        elif legal:
            with pytest.raises(ValidationError):
                await service.transition_status(
                    session,
                    profile,
                    attempt.target,
                    reason=attempt.reason,
                    actor_id=actor_id,
                )
            assert _profile_snapshot(profile) == before_profile
            assert state.snapshot_bookkeeping() == before_bookkeeping
        else:
            with pytest.raises(ConflictError):
                await service.transition_status(
                    session,
                    profile,
                    attempt.target,
                    reason=attempt.reason,
                    actor_id=actor_id,
                )
            assert _profile_snapshot(profile) == before_profile
            assert state.snapshot_bookkeeping() == before_bookkeeping

    before_profile = _profile_snapshot(profile)
    before_bookkeeping = state.snapshot_bookkeeping()
    active_reason = case["active_reason"]
    active_reason_value = active_reason.strip() if active_reason and active_reason.strip() else None
    await_update = {"planning_metadata": {"marker": case["profile_marker"], "updated": True}}
    if profile.status == OperationalStudyStatus.ACTIVE.value and active_reason_value is None:
        with pytest.raises(ValidationError):
            await service.update_profile(
                session, profile, await_update, actor_id=actor_id, reason=active_reason
            )
        assert _profile_snapshot(profile) == before_profile
        assert state.snapshot_bookkeeping() == before_bookkeeping
    else:
        await service.update_profile(
            session, profile, await_update, actor_id=actor_id, reason=active_reason
        )
        assert profile.planning_metadata["updated"] is True
        assert len(state.audits) == before_bookkeeping[1] + 1
        assert len(state.outbox) == before_bookkeeping[2] + 1
        if profile.status == OperationalStudyStatus.ACTIVE.value:
            assert state.audits[-1].reason == active_reason_value

    before_profile = _profile_snapshot(profile)
    before_bookkeeping = state.snapshot_bookkeeping()
    archive_reason = case["archive_reason"]
    archive_reason_value = (
        archive_reason.strip() if archive_reason and archive_reason.strip() else None
    )
    if archive_reason_value is None:
        with pytest.raises(ValidationError):
            await service.archive_study(session, profile, actor_id=actor_id, reason=archive_reason)
        assert _profile_snapshot(profile) == before_profile
        assert state.snapshot_bookkeeping() == before_bookkeeping
    else:
        await service.archive_study(
            session, profile, actor_id=actor_id, reason=archive_reason, correlation_id="archive"
        )
        assert profile.retention_state == "archived"
        assert profile.retention_reason == archive_reason_value
        assert profile.status != "Archived"
        assert state.audits[-1].action == "archive"
        assert state.outbox[-1].event_type == "operational_study_archived"
        if case["archive_again"]:
            after_archive = (_profile_snapshot(profile), state.snapshot_bookkeeping())
            await service.archive_study(session, profile, actor_id=actor_id, reason=archive_reason)
            assert (_profile_snapshot(profile), state.snapshot_bookkeeping()) == after_archive

    assert state.snapshot_clinical() == clinical_before

    before_profile = _profile_snapshot(profile)
    before_bookkeeping = state.snapshot_bookkeeping()
    with pytest.raises(CTMSOwnershipError):
        await service.update_profile(
            session,
            profile,
            {str(case["clinical_field"]): {"attempt": "clinical mutation"}},
            actor_id=actor_id,
            reason="Attempted clinical mutation",
        )
    assert _profile_snapshot(profile) == before_profile
    assert state.snapshot_bookkeeping() == before_bookkeeping
    assert state.snapshot_clinical() == clinical_before

    assert len(state.audits) == len(state.outbox)
    assert all(
        audit.correlation_id == outbox.correlation_id
        for audit, outbox in zip(state.audits, state.outbox, strict=True)
    )
    assert all(outbox.aggregate_id for outbox in state.outbox)
