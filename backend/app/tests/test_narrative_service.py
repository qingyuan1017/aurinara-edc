"""Example-based coverage for PV versioned Case_Narratives.

Feature: pv-safety-module, Task 3.3
Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5

Exercises the NarrativeService against an in-memory database so persistence,
validation, version retention, the Closed-case guard, and the atomic PV safety
Audit_Event are covered end to end. A narrative references a PV-owned
Safety_Case and never mutates an EDC clinical record.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.narrative import CaseNarrative, NarrativeVersion
from app.models.pv.safety_case import CaseState, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.narrative_service import NarrativeService
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
        last_name="Writer",
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


async def _audit_count(session: AsyncSession, action: str | None = None) -> int:
    statement = select(func.count()).select_from(AuditEvent).where(
        AuditEvent.entity_type == "case_narrative"
    )
    if action is not None:
        statement = statement.where(AuditEvent.action == action)
    result = await session.execute(statement)
    return int(result.scalar_one())


async def _open_case(session: AsyncSession) -> tuple[SafetyCase, ActorContext]:
    actor, study, site, subject = await _seed_canonical(session)
    case = await SafetyCaseService().create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=_actor(actor),
    )
    return case, _actor(actor)


async def _closed_case(session: AsyncSession) -> tuple[SafetyCase, ActorContext]:
    """Drive a case to Closed via the permitted lifecycle path."""

    case, actor = await _open_case(session)
    service = SafetyCaseService()
    await service.transition(session, case_id=case.id, target=CaseState.IN_REVIEW, reason=None, actor=actor)
    await service.transition(session, case_id=case.id, target=CaseState.CLOSED, reason=None, actor=actor)
    refreshed = await session.get(SafetyCase, case.id)
    assert refreshed.lifecycle_state == CaseState.CLOSED.value
    return refreshed, actor


# ---------------------------------------------------------------------------
# Create (Requirements 7.1, 7.3, 7.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_narrative_persists_authoring_version_with_audit(db_session: AsyncSession):
    case, actor = await _open_case(db_session)
    service = NarrativeService()

    narrative = await service.create(
        db_session, case_id=case.id, text="  Patient reported a headache.  ", actor=actor
    )

    # Text is stored trimmed and the authoring version is number 1.
    assert narrative.case_id == case.id
    assert narrative.current_text == "Patient reported a headache."
    assert narrative.current_version_number == 1

    versions = (
        await db_session.execute(
            select(NarrativeVersion).where(NarrativeVersion.narrative_id == narrative.id)
        )
    ).scalars().all()
    assert len(versions) == 1
    assert versions[0].version_number == 1
    assert versions[0].text_value == "Patient reported a headache."
    assert versions[0].reason_for_change is None
    assert versions[0].authored_at is not None

    assert await _audit_count(db_session, "create") == 1


@pytest.mark.asyncio
async def test_create_narrative_accepts_max_length_text(db_session: AsyncSession):
    case, actor = await _open_case(db_session)
    service = NarrativeService()

    text = "x" * 20_000
    narrative = await service.create(db_session, case_id=case.id, text=text, actor=actor)
    assert len(narrative.current_text) == 20_000


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   ", "\n\t ", "x" * 20_001])
async def test_create_narrative_rejects_invalid_text(db_session: AsyncSession, text: str):
    case, actor = await _open_case(db_session)
    service = NarrativeService()

    with pytest.raises(ValidationError) as error:
        await service.create(db_session, case_id=case.id, text=text, actor=actor)
    assert error.value.details["field"] == "text"
    # No narrative or change event persisted.
    assert (
        await db_session.execute(select(func.count()).select_from(CaseNarrative))
    ).scalar_one() == 0
    assert await _audit_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_narrative_rejects_unknown_case(db_session: AsyncSession):
    service = NarrativeService()
    with pytest.raises(NotFoundError):
        await service.create(
            db_session,
            case_id=uuid4(),
            text="orphan narrative",
            actor=ActorContext(user_id=uuid4(), request_id=str(uuid4()), correlation_id=str(uuid4())),
        )


# ---------------------------------------------------------------------------
# Revise (Requirements 7.2, 7.3, 7.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_retains_prior_version_and_records_reason(db_session: AsyncSession):
    case, actor = await _open_case(db_session)
    service = NarrativeService()

    narrative = await service.create(db_session, case_id=case.id, text="Initial account.", actor=actor)

    version2 = await service.revise(
        db_session,
        narrative_id=narrative.id,
        text="Revised account with new detail.",
        reason_for_change="  Added lab result  ",
        actor=actor,
    )

    assert version2.version_number == 2
    assert version2.reason_for_change == "Added lab result"

    # Prior version is retained immutably.
    versions = (
        await db_session.execute(
            select(NarrativeVersion)
            .where(NarrativeVersion.narrative_id == narrative.id)
            .order_by(NarrativeVersion.version_number)
        )
    ).scalars().all()
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].text_value == "Initial account."
    assert versions[0].reason_for_change is None

    # Current narrative mirrors the latest version.
    refreshed = await db_session.get(CaseNarrative, narrative.id)
    assert refreshed.current_text == "Revised account with new detail."
    assert refreshed.current_version_number == 2

    assert await _audit_count(db_session, "revise") == 1


@pytest.mark.asyncio
async def test_revise_multiple_times_increments_version(db_session: AsyncSession):
    case, actor = await _open_case(db_session)
    service = NarrativeService()
    narrative = await service.create(db_session, case_id=case.id, text="v1", actor=actor)

    await service.revise(db_session, narrative_id=narrative.id, text="v2", reason_for_change="r2", actor=actor)
    v3 = await service.revise(db_session, narrative_id=narrative.id, text="v3", reason_for_change="r3", actor=actor)

    assert v3.version_number == 3
    count = (
        await db_session.execute(
            select(func.count()).select_from(NarrativeVersion).where(
                NarrativeVersion.narrative_id == narrative.id
            )
        )
    ).scalar_one()
    assert count == 3


@pytest.mark.asyncio
async def test_revise_accepts_boundary_reason_length(db_session: AsyncSession):
    case, actor = await _open_case(db_session)
    service = NarrativeService()
    narrative = await service.create(db_session, case_id=case.id, text="v1", actor=actor)

    version = await service.revise(
        db_session,
        narrative_id=narrative.id,
        text="v2",
        reason_for_change="x" * 4000,
        actor=actor,
    )
    assert version.version_number == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["", "   ", "x" * 4001])
async def test_revise_rejects_invalid_reason(db_session: AsyncSession, reason: str):
    case, actor = await _open_case(db_session)
    service = NarrativeService()
    narrative = await service.create(db_session, case_id=case.id, text="v1", actor=actor)

    with pytest.raises(ValidationError) as error:
        await service.revise(
            db_session,
            narrative_id=narrative.id,
            text="v2",
            reason_for_change=reason,
            actor=actor,
        )
    assert error.value.details["reason"] == "INVALID_REASON_FOR_CHANGE"
    # Existing narrative state preserved: still one version and original text.
    refreshed = await db_session.get(CaseNarrative, narrative.id)
    assert refreshed.current_text == "v1"
    assert refreshed.current_version_number == 1
    assert (
        await db_session.execute(
            select(func.count()).select_from(NarrativeVersion).where(
                NarrativeVersion.narrative_id == narrative.id
            )
        )
    ).scalar_one() == 1
    assert await _audit_count(db_session, "revise") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   ", "x" * 20_001])
async def test_revise_rejects_invalid_text_and_preserves_state(db_session: AsyncSession, text: str):
    case, actor = await _open_case(db_session)
    service = NarrativeService()
    narrative = await service.create(db_session, case_id=case.id, text="original", actor=actor)

    with pytest.raises(ValidationError) as error:
        await service.revise(
            db_session,
            narrative_id=narrative.id,
            text=text,
            reason_for_change="valid reason",
            actor=actor,
        )
    assert error.value.details["field"] == "text"
    refreshed = await db_session.get(CaseNarrative, narrative.id)
    assert refreshed.current_text == "original"
    assert refreshed.current_version_number == 1


@pytest.mark.asyncio
async def test_revise_rejects_unknown_narrative(db_session: AsyncSession):
    service = NarrativeService()
    with pytest.raises(NotFoundError):
        await service.revise(
            db_session,
            narrative_id=uuid4(),
            text="v2",
            reason_for_change="reason",
            actor=ActorContext(user_id=uuid4(), request_id=str(uuid4()), correlation_id=str(uuid4())),
        )


# ---------------------------------------------------------------------------
# Closed-case rejection (Requirement 7.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_rejected_when_case_closed(db_session: AsyncSession):
    case, actor = await _closed_case(db_session)
    service = NarrativeService()

    with pytest.raises(ValidationError) as error:
        await service.create(db_session, case_id=case.id, text="late narrative", actor=actor)
    assert error.value.details["reason"] == "CASE_CLOSED"
    assert (
        await db_session.execute(select(func.count()).select_from(CaseNarrative))
    ).scalar_one() == 0
    assert await _audit_count(db_session) == 0


@pytest.mark.asyncio
async def test_revise_rejected_when_case_closed_preserves_state(db_session: AsyncSession):
    # Author a narrative while the case is open, then close the case.
    case, actor = await _open_case(db_session)
    service = NarrativeService()
    narrative = await service.create(db_session, case_id=case.id, text="pre-close", actor=actor)

    sc = SafetyCaseService()
    await sc.transition(db_session, case_id=case.id, target=CaseState.IN_REVIEW, reason=None, actor=actor)
    await sc.transition(db_session, case_id=case.id, target=CaseState.CLOSED, reason=None, actor=actor)

    with pytest.raises(ValidationError) as error:
        await service.revise(
            db_session,
            narrative_id=narrative.id,
            text="post-close edit",
            reason_for_change="should be rejected",
            actor=actor,
        )
    assert error.value.details["reason"] == "CASE_CLOSED"
    # Existing narrative state preserved.
    refreshed = await db_session.get(CaseNarrative, narrative.id)
    assert refreshed.current_text == "pre-close"
    assert refreshed.current_version_number == 1
    assert await _audit_count(db_session, "revise") == 0
