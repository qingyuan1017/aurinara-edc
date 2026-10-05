"""Example-based coverage for PV Safety_Case intake and adverse-event capture.

Feature: pv-safety-module, Task 2.2
Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10

Exercises the SafetyCaseService against an in-memory database so persistence,
validation, globally-unique identifier generation, and the atomic PV safety
Audit_Event are covered end to end. PV references canonical Study/Site and the
EDC Subject_Reference and never mutates the clinical subject record.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseState,
    SafetyCase,
)
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.pv_ownership_guard import PVOwnershipError
from app.services.safety_case_service import SafetyCaseService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_canonical(session: AsyncSession) -> tuple[User, Study, Site, Subject]:
    actor = User(
        email=f"pv-{uuid4()}@example.test",
        first_name="PV",
        last_name="Associate",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()

    study = Study(study_code=f"PV-STUDY-{uuid4()}", title="Safety study", created_by=actor.id)
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
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()
    return actor, study, site, subject


def _actor(user: User) -> ActorContext:
    return ActorContext(
        user_id=user.id, request_id=str(uuid4()), correlation_id=str(uuid4())
    )


async def _audit_count(session: AsyncSession, entity_type: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_type == entity_type
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Safety_Case creation (Requirements 3.1, 3.2, 3.8, 3.10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_case_persists_one_case_with_audit(db_session: AsyncSession):
    actor, study, site, subject = await _seed_canonical(db_session)
    service = SafetyCaseService()

    case = await service.create_case(
        db_session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=_actor(actor),
    )

    assert case.study_id == study.id
    assert case.site_id == site.id
    assert case.subject_reference == subject.id
    assert case.lifecycle_state == CaseState.OPEN.value
    assert case.case_identifier

    cases = (await db_session.execute(select(SafetyCase))).scalars().all()
    assert len(cases) == 1
    assert await _audit_count(db_session, "safety_case") == 1

    # The referenced EDC clinical subject is untouched (Requirement 3.10).
    refreshed_subject = await db_session.get(Subject, subject.id)
    assert refreshed_subject.subject_number == "S-001"


@pytest.mark.asyncio
async def test_create_case_generates_globally_unique_identifiers(db_session: AsyncSession):
    actor, study, site, subject = await _seed_canonical(db_session)
    service = SafetyCaseService()

    first = await service.create_case(
        db_session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=_actor(actor),
    )
    second = await service.create_case(
        db_session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=_actor(actor),
    )
    assert first.case_identifier != second.case_identifier


@pytest.mark.asyncio
async def test_create_case_rejects_unknown_subject_reference(db_session: AsyncSession):
    actor, study, site, _subject = await _seed_canonical(db_session)
    service = SafetyCaseService()

    with pytest.raises(NotFoundError) as error:
        await service.create_case(
            db_session,
            study_id=study.id,
            site_id=site.id,
            subject_reference=uuid4(),
            case_type="Adverse Event",
            payload={},
            actor=_actor(actor),
        )
    assert error.value.details["reason"] == "RECORD_NOT_FOUND"
    assert (await _audit_count(db_session, "safety_case")) == 0
    assert (await db_session.execute(select(func.count()).select_from(SafetyCase))).scalar_one() == 0


@pytest.mark.asyncio
async def test_create_case_rejects_duplicate_identifier(db_session: AsyncSession):
    actor, study, site, subject = await _seed_canonical(db_session)
    service = SafetyCaseService()

    await service.create_case(
        db_session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={"case_identifier": "PV-DUP-1"},
        actor=_actor(actor),
    )

    with pytest.raises(ConflictError) as error:
        await service.create_case(
            db_session,
            study_id=study.id,
            site_id=site.id,
            subject_reference=subject.id,
            case_type="Adverse Event",
            payload={"case_identifier": "PV-DUP-1"},
            actor=_actor(actor),
        )
    assert error.value.details["reason"] == "DUPLICATE_CASE_IDENTIFIER"
    # Exactly the original case remains.
    count = (await db_session.execute(select(func.count()).select_from(SafetyCase))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_create_case_rejects_edc_owned_payload(db_session: AsyncSession):
    actor, study, site, subject = await _seed_canonical(db_session)
    service = SafetyCaseService()

    with pytest.raises(PVOwnershipError):
        await service.create_case(
            db_session,
            study_id=study.id,
            site_id=site.id,
            subject_reference=subject.id,
            case_type="Adverse Event",
            payload={"clinical_subject": {"subject_number": "X"}},
            actor=_actor(actor),
        )
    assert (await db_session.execute(select(func.count()).select_from(SafetyCase))).scalar_one() == 0


# ---------------------------------------------------------------------------
# Adverse_Event_Record capture (Requirements 3.3, 3.4, 3.7, 3.9)
# ---------------------------------------------------------------------------


async def _create_case(service: SafetyCaseService, session: AsyncSession) -> SafetyCase:
    actor, study, site, subject = await _seed_canonical(session)
    case = await service.create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=_actor(actor),
    )
    case._actor = _actor(actor)  # type: ignore[attr-defined]
    return case


@pytest.mark.asyncio
async def test_add_adverse_event_persists_valid_record_with_audit(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _create_case(service, db_session)

    record = await service.add_adverse_event(
        db_session,
        case_id=case.id,
        payload={
            "verbatim_term": "headache",
            "onset_date": "2026-01-01",
            "outcome": "Recovered",
            "resolution_date": "2026-01-05",
        },
        actor=case._actor,  # type: ignore[attr-defined]
    )

    assert record.case_id == case.id
    assert record.verbatim_term == "headache"
    assert record.onset_date == date(2026, 1, 1)
    assert record.resolution_date == date(2026, 1, 5)
    assert await _audit_count(db_session, "adverse_event_record") == 1


@pytest.mark.asyncio
async def test_add_adverse_event_allows_omitted_resolution(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _create_case(service, db_session)

    record = await service.add_adverse_event(
        db_session,
        case_id=case.id,
        payload={
            "verbatim_term": "nausea",
            "onset_date": date(2026, 2, 1),
            "outcome": "Ongoing",
        },
        actor=case._actor,  # type: ignore[attr-defined]
    )
    assert record.resolution_date is None


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [0, 201])
async def test_add_adverse_event_rejects_invalid_verbatim_length(
    db_session: AsyncSession, length: int
):
    service = SafetyCaseService()
    case = await _create_case(service, db_session)

    with pytest.raises(ValidationError) as error:
        await service.add_adverse_event(
            db_session,
            case_id=case.id,
            payload={
                "verbatim_term": "x" * length,
                "onset_date": "2026-01-01",
                "outcome": "Recovered",
            },
            actor=case._actor,  # type: ignore[attr-defined]
        )
    assert error.value.details["field"] == "verbatim_term"
    assert (
        await db_session.execute(select(func.count()).select_from(AdverseEventRecord))
    ).scalar_one() == 0
    assert await _audit_count(db_session, "adverse_event_record") == 0


@pytest.mark.asyncio
async def test_add_adverse_event_accepts_verbatim_boundaries(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _create_case(service, db_session)

    for term in ("a", "b" * 200):
        record = await service.add_adverse_event(
            db_session,
            case_id=case.id,
            payload={
                "verbatim_term": term,
                "onset_date": "2026-01-01",
                "outcome": "Recovered",
            },
            actor=case._actor,  # type: ignore[attr-defined]
        )
        assert record.verbatim_term == term


@pytest.mark.asyncio
async def test_add_adverse_event_rejects_resolution_before_onset(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _create_case(service, db_session)

    with pytest.raises(ValidationError) as error:
        await service.add_adverse_event(
            db_session,
            case_id=case.id,
            payload={
                "verbatim_term": "rash",
                "onset_date": "2026-03-10",
                "outcome": "Recovered",
                "resolution_date": "2026-03-01",
            },
            actor=case._actor,  # type: ignore[attr-defined]
        )
    assert error.value.details["field"] == "resolution_date"
    assert (
        await db_session.execute(select(func.count()).select_from(AdverseEventRecord))
    ).scalar_one() == 0
    assert await _audit_count(db_session, "adverse_event_record") == 0


@pytest.mark.asyncio
async def test_add_adverse_event_rejects_unknown_case(db_session: AsyncSession):
    service = SafetyCaseService()

    with pytest.raises(NotFoundError):
        await service.add_adverse_event(
            db_session,
            case_id=uuid4(),
            payload={
                "verbatim_term": "cough",
                "onset_date": "2026-01-01",
                "outcome": "Recovered",
            },
            actor=ActorContext(
                user_id=uuid4(), request_id=str(uuid4()), correlation_id=str(uuid4())
            ),
        )


# ---------------------------------------------------------------------------
# Case lifecycle transitions (Requirements 4.1, 4.2, 4.9) — Task 2.4
# ---------------------------------------------------------------------------


from app.models.pv.safety_case import (  # noqa: E402
    CaseVersion,
    CaseVersionKind,
    CaseVersionStatus,
)


async def _open_case(service: SafetyCaseService, session: AsyncSession) -> SafetyCase:
    actor, study, site, subject = await _seed_canonical(session)
    case = await service.create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=_actor(actor),
    )
    case._actor = _actor(actor)  # type: ignore[attr-defined]
    return case


@pytest.mark.asyncio
async def test_transition_open_to_in_review(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)

    updated = await service.transition(
        db_session,
        case_id=case.id,
        target=CaseState.IN_REVIEW,
        reason=None,
        actor=case._actor,  # type: ignore[attr-defined]
    )
    assert updated.lifecycle_state == CaseState.IN_REVIEW.value
    # Exactly one transition audit event on top of the create event.
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.entity_type == "safety_case", AuditEvent.action == "transition")
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_transition_full_permitted_path(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    async def go(target: CaseState) -> None:
        await service.transition(db_session, case_id=case.id, target=target, reason=None, actor=actor)

    await go(CaseState.IN_REVIEW)
    await go(CaseState.READY_TO_REPORT)
    await go(CaseState.REPORTED)
    await go(CaseState.FOLLOW_UP_REQUIRED)
    await go(CaseState.IN_REVIEW)
    await go(CaseState.CLOSED)
    await go(CaseState.REOPENED)

    refreshed = await db_session.get(SafetyCase, case.id)
    assert refreshed.lifecycle_state == CaseState.REOPENED.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [CaseState.CLOSED, CaseState.REPORTED, CaseState.REOPENED, CaseState.FOLLOW_UP_REQUIRED],
)
async def test_transition_rejects_illegal_transition_from_open(
    db_session: AsyncSession, target: CaseState
):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)

    with pytest.raises(ValidationError) as error:
        await service.transition(
            db_session,
            case_id=case.id,
            target=target,
            reason=None,
            actor=case._actor,  # type: ignore[attr-defined]
        )
    assert error.value.details["reason"] == "TRANSITION_NOT_PERMITTED"
    # State and content are unchanged and no transition audit event was written.
    refreshed = await db_session.get(SafetyCase, case.id)
    assert refreshed.lifecycle_state == CaseState.OPEN.value
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "transition")
        )
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_transition_rejects_unknown_case(db_session: AsyncSession):
    service = SafetyCaseService()
    with pytest.raises(NotFoundError):
        await service.transition(
            db_session,
            case_id=uuid4(),
            target=CaseState.IN_REVIEW,
            reason=None,
            actor=ActorContext(user_id=uuid4(), request_id=str(uuid4()), correlation_id=str(uuid4())),
        )


# ---------------------------------------------------------------------------
# Case_Version submission (Requirements 4.3, 4.4, 4.5, 4.8, 4.9) — Task 2.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_initial_version_is_sequence_one(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    await service.add_adverse_event(
        db_session,
        case_id=case.id,
        payload={"verbatim_term": "headache", "onset_date": "2026-01-01", "outcome": "Recovered"},
        actor=case._actor,  # type: ignore[attr-defined]
    )

    version = await service.submit_version(
        db_session, case_id=case.id, actor=case._actor  # type: ignore[attr-defined]
    )
    assert version.sequence_number == 1
    assert version.version_kind == CaseVersionKind.INITIAL.value
    assert version.status == CaseVersionStatus.SUBMITTED.value
    assert version.captured_content["case_identifier"] == case.case_identifier
    assert len(version.captured_content["adverse_events"]) == 1
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.entity_type == "case_version", AuditEvent.action == "submit")
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_submit_followup_version_is_max_plus_one(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    first = await service.submit_version(db_session, case_id=case.id, actor=actor)
    second = await service.submit_version(db_session, case_id=case.id, actor=actor)
    third = await service.submit_version(db_session, case_id=case.id, actor=actor)

    assert [first.sequence_number, second.sequence_number, third.sequence_number] == [1, 2, 3]
    assert first.version_kind == CaseVersionKind.INITIAL.value
    assert second.version_kind == CaseVersionKind.FOLLOW_UP.value
    assert third.version_kind == CaseVersionKind.FOLLOW_UP.value


@pytest.mark.asyncio
async def test_submitted_version_content_immutable_after_case_change(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    version = await service.submit_version(db_session, case_id=case.id, actor=actor)
    captured_before = dict(version.captured_content)

    # Change the live case; the prior submitted snapshot must not change.
    await service.change_submitted_data(
        db_session,
        case_id=case.id,
        changes={"case_type": "Follow-up Report"},
        reason_for_change="Reclassified after review",
        actor=actor,
    )
    refreshed = await db_session.get(CaseVersion, version.id)
    assert refreshed.captured_content == captured_before
    assert refreshed.captured_content["case_type"] == "Adverse Event"


@pytest.mark.asyncio
async def test_prior_submitted_versions_retained(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    await service.submit_version(db_session, case_id=case.id, actor=actor)
    await service.submit_version(db_session, case_id=case.id, actor=actor)

    count = (
        await db_session.execute(
            select(func.count()).select_from(CaseVersion).where(CaseVersion.case_id == case.id)
        )
    ).scalar_one()
    assert count == 2


# ---------------------------------------------------------------------------
# Post-submission changes with Reason_For_Change (Requirements 4.6, 4.7) — Task 2.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_submitted_data_persists_with_reason(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    await service.change_submitted_data(
        db_session,
        case_id=case.id,
        changes={"case_type": "Serious Adverse Event"},
        reason_for_change="Upgraded seriousness after physician review",
        actor=actor,
    )
    refreshed = await db_session.get(SafetyCase, case.id)
    assert refreshed.case_type == "Serious Adverse Event"

    audit = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "change_submitted_data")
        )
    ).scalar_one()
    assert audit.reason == "Upgraded seriousness after physician review"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["", "   ", "x" * 4001])
async def test_change_submitted_data_rejects_invalid_reason(
    db_session: AsyncSession, reason: str
):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    with pytest.raises(ValidationError) as error:
        await service.change_submitted_data(
            db_session,
            case_id=case.id,
            changes={"case_type": "Serious Adverse Event"},
            reason_for_change=reason,
            actor=actor,
        )
    assert error.value.details["reason"] == "INVALID_REASON_FOR_CHANGE"
    # Data unchanged; no change event recorded.
    refreshed = await db_session.get(SafetyCase, case.id)
    assert refreshed.case_type == "Adverse Event"
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "change_submitted_data")
        )
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_change_submitted_data_accepts_boundary_reason_length(db_session: AsyncSession):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    await service.change_submitted_data(
        db_session,
        case_id=case.id,
        changes={"case_type": "Serious Adverse Event"},
        reason_for_change="x" * 4000,
        actor=actor,
    )
    refreshed = await db_session.get(SafetyCase, case.id)
    assert refreshed.case_type == "Serious Adverse Event"


@pytest.mark.asyncio
async def test_change_submitted_data_rejects_modifying_submitted_version(
    db_session: AsyncSession,
):
    service = SafetyCaseService()
    case = await _open_case(service, db_session)
    actor = case._actor  # type: ignore[attr-defined]

    version = await service.submit_version(db_session, case_id=case.id, actor=actor)

    with pytest.raises(ValidationError) as error:
        await service.change_submitted_data(
            db_session,
            case_id=case.id,
            changes={"version_id": str(version.id), "case_type": "Changed"},
            reason_for_change="Attempt to edit a submitted version",
            actor=actor,
        )
    assert error.value.details["reason"] == "VERSION_IMMUTABLE"
    refreshed = await db_session.get(SafetyCase, case.id)
    assert refreshed.case_type == "Adverse Event"
