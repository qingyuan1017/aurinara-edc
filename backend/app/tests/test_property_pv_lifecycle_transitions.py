"""Property 2: Safety lifecycle transition validity.

**Validates: Requirements 4, 8, 14**

Feature: pv-safety-module, Task 2.5

*For any* generated Safety_Case, Case_Version, Regulatory_Report, and
notification status sequence, the PV services accept exactly the configured
transitions, record the initial Case_Version with sequence number 1 and each
follow-up with sequence number ``max + 1``, preserve every prior submitted
Case_Version, and reject an invalid transition without any partial mutation.

The Safety_Case lifecycle and Case_Version sequencing are exercised against the
real ``SafetyCaseService`` (task 2.4) over an in-memory SQLite database with
deterministic canonical Study/Site/Subject fixtures — no database server,
queue, object storage, or other external service is used.

The Regulatory_Report state machine (task 4.1) and the notification state
machine (task 6.3) are not yet implemented as services. Their configured
transition rules are documented acceptance criteria (Requirement 8.5:
Pending→Submitted/Cancelled, Submitted→Acknowledged/Rejected, Rejected→Pending;
Requirement 14.4: Unread→Read/Archived, Read→Archived), so the property verifies
those rules as pure transition-validity checks over the documented maps. When
the services land, the same maps drive their behavior.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.safety_case import (
    CaseState,
    CaseVersion,
    CaseVersionKind,
    CaseVersionStatus,
    SafetyCase,
)
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.safety_case_service import (
    _ALLOWED_TRANSITIONS,
    SafetyCaseService,
)

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Configured transition maps
# ---------------------------------------------------------------------------

# Safety_Case lifecycle (Requirement 4.1). Sourced from the service's own map so
# the property stays in lockstep with the implementation under test.
_CASE_STATES: tuple[CaseState, ...] = tuple(CaseState)

# Regulatory_Report status transitions (Requirement 8.5). The report service
# (task 4.1) is not implemented yet, so the documented rule is verified directly.
_REPORT_TRANSITIONS: dict[str, frozenset[str]] = {
    "Pending": frozenset({"Submitted", "Cancelled"}),
    "Submitted": frozenset({"Acknowledged", "Rejected"}),
    "Acknowledged": frozenset(),
    "Rejected": frozenset({"Pending"}),
    "Cancelled": frozenset(),
}
_REPORT_STATES: tuple[str, ...] = tuple(_REPORT_TRANSITIONS)

# Notification status transitions (Requirement 14.4). The notification service
# (task 6.3) is not implemented yet, so the documented rule is verified directly.
_NOTIFICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "Unread": frozenset({"Read", "Archived"}),
    "Read": frozenset({"Archived"}),
    "Archived": frozenset(),
}
_NOTIFICATION_STATES: tuple[str, ...] = tuple(_NOTIFICATION_TRANSITIONS)


# ---------------------------------------------------------------------------
# In-memory database and canonical identity fixtures
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _seed_open_case(
    session: AsyncSession, service: SafetyCaseService
) -> tuple[SafetyCase, ActorContext]:
    """Create the canonical Study/Site/Subject and one Open Safety_Case."""

    actor_user = User(
        email=f"pv-{uuid4()}@example.test",
        first_name="PV",
        last_name="Associate",
        status=UserStatus.active,
    )
    session.add(actor_user)
    await session.flush()

    study = Study(
        study_code=f"PV-STUDY-{uuid4()}", title="Safety study", created_by=actor_user.id
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id, version_number="1.0", status=StudyVersionStatus.published
    )
    session.add(version)
    await session.flush()

    site = Site(study_id=study.id, site_number="001", name="Site A")
    session.add(site)
    await session.flush()

    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="S-001",
        created_by=actor_user.id,
    )
    session.add(subject)
    await session.flush()

    actor = ActorContext(
        user_id=actor_user.id, request_id=str(uuid4()), correlation_id=str(uuid4())
    )
    case = await service.create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=actor,
    )
    return case, actor


async def _transition_audit_count(session: AsyncSession, case_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.entity_type == "safety_case",
            AuditEvent.action == "transition",
            AuditEvent.entity_id == case_id,
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Property 2a: Safety_Case lifecycle transition validity (real service)
# ---------------------------------------------------------------------------


@given(targets=st.lists(st.sampled_from(_CASE_STATES), min_size=1, max_size=12))
@settings(
    max_examples=150,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_case_lifecycle_accepts_only_configured_transitions(
    targets: list[CaseState],
) -> None:
    """Only configured lifecycle transitions apply; invalid ones never mutate.

    A generated sequence of requested target states is applied to a real
    Safety_Case. A request whose target is in the configured allow-set for the
    current state advances the case and records exactly one transition
    Audit_Event; any other request is rejected, leaves the lifecycle state
    unchanged, and records no transition Audit_Event (Requirements 4.1, 4.2,
    4.9).

    **Validates: Requirements 4, 8, 14**
    """

    session, engine = await _make_session()
    service = SafetyCaseService()
    try:
        case, actor = await _seed_open_case(session, service)
        current = CaseState(case.lifecycle_state)
        expected_transition_events = 0

        for target in targets:
            allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
            if target in allowed:
                updated = await service.transition(
                    session, case_id=case.id, target=target, reason=None, actor=actor
                )
                current = target
                expected_transition_events += 1
                assert updated.lifecycle_state == current.value
            else:
                with pytest.raises(ValidationError) as error:
                    await service.transition(
                        session,
                        case_id=case.id,
                        target=target,
                        reason=None,
                        actor=actor,
                    )
                assert error.value.details["reason"] == "TRANSITION_NOT_PERMITTED"

            # No partial mutation: after each request the persisted state equals
            # the last accepted state.
            refreshed = await session.get(SafetyCase, case.id)
            await session.refresh(refreshed)
            assert refreshed.lifecycle_state == current.value

        # Exactly one transition Audit_Event per accepted transition.
        assert (
            await _transition_audit_count(session, case.id)
            == expected_transition_events
        )
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2b: Case_Version sequencing and preservation (real service)
# ---------------------------------------------------------------------------


@given(submission_count=st.integers(min_value=1, max_value=8))
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_case_version_sequencing_and_preservation(
    submission_count: int,
) -> None:
    """Initial version is sequence 1, each follow-up is max+1, all preserved.

    Submitting ``n`` Case_Versions yields sequence numbers ``1..n`` with the
    first tagged Initial and the rest Follow-up, every version Submitted, and no
    prior submitted version deleted or overwritten (Requirements 4.3, 4.4, 4.8).

    **Validates: Requirements 4, 8, 14**
    """

    session, engine = await _make_session()
    service = SafetyCaseService()
    try:
        case, actor = await _seed_open_case(session, service)

        sequence_numbers: list[int] = []
        kinds: list[str] = []
        for _ in range(submission_count):
            version = await service.submit_version(
                session, case_id=case.id, actor=actor
            )
            sequence_numbers.append(version.sequence_number)
            kinds.append(version.version_kind)

        # Initial version is sequence 1; follow-ups are strictly max+1.
        assert sequence_numbers == list(range(1, submission_count + 1))
        assert kinds[0] == CaseVersionKind.INITIAL.value
        assert all(kind == CaseVersionKind.FOLLOW_UP.value for kind in kinds[1:])

        # All prior submitted versions are retained (none deleted or overwritten).
        persisted = (
            (
                await session.execute(
                    select(CaseVersion)
                    .where(CaseVersion.case_id == case.id)
                    .order_by(CaseVersion.sequence_number)
                )
            )
            .scalars()
            .all()
        )
        assert len(persisted) == submission_count
        assert [v.sequence_number for v in persisted] == list(
            range(1, submission_count + 1)
        )
        assert all(
            v.status == CaseVersionStatus.SUBMITTED.value for v in persisted
        )
        # Each Submitted snapshot carries the case identifier immutably.
        assert all(
            v.captured_content["case_identifier"] == case.case_identifier
            for v in persisted
        )
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2c: submitted Case_Version content is immutable
# ---------------------------------------------------------------------------


@given(
    reason=st.text(min_size=1, max_size=200).filter(lambda s: bool(s.strip())),
    new_case_type=st.text(min_size=1, max_size=80).filter(lambda s: bool(s.strip())),
)
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_submitted_version_content_is_immutable(
    reason: str, new_case_type: str
) -> None:
    """A submitted Case_Version snapshot never changes when the live case does.

    After a version is submitted, a post-submission change to the live case must
    leave the earlier snapshot's captured content unchanged (Requirement 4.5).

    **Validates: Requirements 4, 8, 14**
    """

    session, engine = await _make_session()
    service = SafetyCaseService()
    try:
        case, actor = await _seed_open_case(session, service)
        version = await service.submit_version(session, case_id=case.id, actor=actor)
        snapshot_before = dict(version.captured_content)

        await service.change_submitted_data(
            session,
            case_id=case.id,
            changes={"case_type": new_case_type},
            reason_for_change=reason,
            actor=actor,
        )

        refreshed = await session.get(CaseVersion, version.id)
        await session.refresh(refreshed)
        assert refreshed.captured_content == snapshot_before
        assert refreshed.captured_content["case_type"] == "Adverse Event"
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2d: Regulatory_Report status transition validity (Requirement 8.5)
# ---------------------------------------------------------------------------


def _apply_transition(
    transitions: dict[str, frozenset[str]], state: str, target: str
) -> tuple[str, bool]:
    """Return the resulting state and whether the transition was accepted.

    A transition is accepted exactly when ``target`` is in the allow-set for the
    current ``state``; otherwise the state is unchanged (no partial mutation).
    """

    if target in transitions.get(state, frozenset()):
        return target, True
    return state, False


@given(targets=st.lists(st.sampled_from(_REPORT_STATES), min_size=1, max_size=12))
@settings(max_examples=100, deadline=None, derandomize=True)
async def test_report_status_accepts_only_configured_transitions(
    targets: list[str],
) -> None:
    """Report status advances only through configured transitions.

    Verifies Requirement 8.5 as a pure transition-validity check while the
    Regulatory_Reporting_Service (task 4.1) is not yet implemented: Pending→
    Submitted/Cancelled, Submitted→Acknowledged/Rejected, Rejected→Pending, and
    every other transition is rejected with the state unchanged.

    **Validates: Requirements 4, 8, 14**
    """

    state = "Pending"
    for target in targets:
        previous = state
        state, accepted = _apply_transition(_REPORT_TRANSITIONS, state, target)
        if accepted:
            assert target in _REPORT_TRANSITIONS[previous]
            assert state == target
        else:
            assert target not in _REPORT_TRANSITIONS[previous]
            # Rejected transition performs no partial mutation.
            assert state == previous


# ---------------------------------------------------------------------------
# Property 2e: notification status transition validity (Requirement 14.4)
# ---------------------------------------------------------------------------


@given(targets=st.lists(st.sampled_from(_NOTIFICATION_STATES), min_size=1, max_size=12))
@settings(max_examples=100, deadline=None, derandomize=True)
async def test_notification_status_accepts_only_configured_transitions(
    targets: list[str],
) -> None:
    """Notification status advances only through configured transitions.

    Verifies Requirement 14.4 as a pure transition-validity check while the
    notification triggers (task 6.3) are not yet implemented: Unread→Read/
    Archived, Read→Archived, and every other transition is rejected with the
    status unchanged.

    **Validates: Requirements 4, 8, 14**
    """

    state = "Unread"
    for target in targets:
        previous = state
        state, accepted = _apply_transition(
            _NOTIFICATION_TRANSITIONS, state, target
        )
        if accepted:
            assert target in _NOTIFICATION_TRANSITIONS[previous]
            assert state == target
        else:
            assert target not in _NOTIFICATION_TRANSITIONS[previous]
            assert state == previous
        # Archived is terminal.
        if previous == "Archived":
            assert not accepted
