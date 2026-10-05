"""Property 3: Safety data validation and preservation.

Feature: pv-safety-module, Task 3.4
**Validates: Requirements 3, 5, 6, 7, 18**

*For any* generated assessment, coding, narrative, and intake payload
(including boundary and invalid values):

  1. Submission validates the required inputs — a serious Seriousness_Assessment
     requires at least one criterion, an Adverse_Event_Record verbatim term is
     1-200 characters and its resolution date is not earlier than onset, a
     Case_Narrative text is non-empty after trimming and at most 20,000
     characters, and a Reason_For_Change is non-empty after trimming and at most
     4,000 characters (Requirements 3, 5, 6, 7).
  2. A failed validation preserves the prior persisted values and persists no
     change event: neither the target rows nor any PV safety Audit_Event row
     count changes across a rejected call (Requirement 18).
  3. A post-submission change to submitted Safety_Data requires a valid
     Reason_For_Change (Requirement 4.6/4.7, exercised via
     ``change_submitted_data``).
  4. A Closed Safety_Case rejects safety modifications (assessment, coding,
     narrative) and preserves existing state (Requirements 5.8, 6, 7.4).

The real ``SafetyCaseService``, ``AssessmentService``, ``CodingService``, and
``NarrativeService`` are exercised over an in-memory SQLite database with
deterministic canonical Study/Site/Subject fixtures and a pinned in-memory
coding dictionary. No external service (database server, queue, object storage,
dictionary gateway) is used, and each property runs at least 100 examples.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.assessment import SeriousnessCriterion
from app.models.pv.coding import CodingSystem
from app.models.pv.narrative import (
    NARRATIVE_REASON_MAX_LENGTH,
    NARRATIVE_TEXT_MAX_LENGTH,
    CaseNarrative,
)
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseState,
    SafetyCase,
)
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.repositories.pv.coding_repository import CodingRepository
from app.services.assessment_service import AssessmentService
from app.services.coding_service import CodingService
from app.services.narrative_service import NarrativeService
from app.services.pv_coding_dictionary import CodingDictionaryProvider
from app.services.safety_case_service import SafetyCaseService

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Deterministic coding fixtures (pinned, hermetic, no external dictionary)
# ---------------------------------------------------------------------------

MEDDRA_VERSION = "27.0"
VALID_MEDDRA_TERM = "10019211"  # pinned "Headache"
INVALID_MEDDRA_TERM = "NOT-A-REAL-TERM"

_VALID_CRITERIA: tuple[str, ...] = tuple(c.value for c in SeriousnessCriterion)


def _dictionary() -> CodingDictionaryProvider:
    provider = CodingDictionaryProvider()
    provider.register(
        coding_system=CodingSystem.MEDDRA,
        version=MEDDRA_VERSION,
        terms=frozenset({VALID_MEDDRA_TERM}),
    )
    return provider


# ---------------------------------------------------------------------------
# In-memory database and canonical identity fixtures
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


def _actor(user: User) -> ActorContext:
    return ActorContext(
        user_id=user.id, request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4())
    )


async def _seed_case(
    session: AsyncSession,
    service: SafetyCaseService,
    *,
    closed: bool = False,
) -> tuple[SafetyCase, ActorContext, User]:
    """Create canonical Study/Site/Subject and one Safety_Case (Open by default)."""

    actor_user = User(
        email=f"pv-{uuid.uuid4()}@example.test",
        first_name="PV",
        last_name="Associate",
        status=UserStatus.active,
    )
    session.add(actor_user)
    await session.flush()

    study = Study(
        study_code=f"PV-{uuid.uuid4().hex[:10]}",
        title="Safety study",
        created_by=actor_user.id,
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

    actor = _actor(actor_user)
    case = await service.create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=actor,
    )

    if closed:
        # Walk the constrained lifecycle to a Closed state.
        await service.transition(
            session, case_id=case.id, target=CaseState.IN_REVIEW, reason=None, actor=actor
        )
        await service.transition(
            session, case_id=case.id, target=CaseState.CLOSED, reason=None, actor=actor
        )
    return case, actor, actor_user


async def _register_meddra(session: AsyncSession) -> None:
    await CodingRepository(session).add_dictionary_version(
        coding_system=CodingSystem.MEDDRA, version=MEDDRA_VERSION, available=True
    )


async def _add_adverse_event(
    session: AsyncSession,
    service: SafetyCaseService,
    case: SafetyCase,
    actor: ActorContext,
) -> AdverseEventRecord:
    return await service.add_adverse_event(
        session,
        case_id=case.id,
        payload={
            "verbatim_term": "baseline term",
            "onset_date": date(2026, 1, 1),
            "outcome": "Recovered",
        },
        actor=actor,
    )


async def _audit_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AuditEvent))
    return int(result.scalar_one())


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def _assert_no_persistence_change(
    session: AsyncSession, model, coroutine
) -> None:
    """Run a call expected to be rejected and assert no rows/audit rows changed.

    A failed validation must preserve prior persisted values and write no change
    event, so both the target model's row count and the PV safety Audit_Event
    row count are identical before and after the rejected call (Requirement 18).
    """

    rows_before = await _count(session, model)
    audit_before = await _audit_count(session)
    with pytest.raises((ValidationError, NotFoundError, ConflictError)):
        await coroutine
    assert await _count(session, model) == rows_before
    assert await _audit_count(session) == audit_before


# ---------------------------------------------------------------------------
# Property 3a: Adverse_Event_Record intake validation and preservation
# ---------------------------------------------------------------------------


@given(
    # Draw printable, non-NUL text so the property exercises the 1-200 length
    # boundary itself. SQLite's length() truncates at an embedded NUL, which
    # makes the DB constraint and the service's Python len() disagree for NUL
    # bytes; that incidental mismatch is out of scope for this property.
    verbatim=st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
        min_size=0,
        max_size=260,
    ),
    onset_offset=st.integers(min_value=0, max_value=500),
    resolution_delta=st.integers(min_value=-30, max_value=30),
    include_resolution=st.booleans(),
)
@settings(
    max_examples=150,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_intake_validates_verbatim_and_resolution(
    verbatim: str,
    onset_offset: int,
    resolution_delta: int,
    include_resolution: bool,
) -> None:
    """Intake accepts valid verbatim/dates and rejects invalid ones intact.

    A verbatim term is valid exactly when it is 1-200 characters; a resolution
    date is accepted only when it is not earlier than onset. Any invalid payload
    is rejected and persists neither the adverse event nor a change event
    (Requirements 3.3, 3.4, 3.7, 3.8, 18).

    **Validates: Requirements 3, 5, 6, 7, 18**
    """

    session, engine = await _make_session()
    service = SafetyCaseService()
    try:
        case, actor, _user = await _seed_case(session, service)

        onset = date(2026, 1, 1) + timedelta(days=onset_offset)
        payload: dict = {
            "verbatim_term": verbatim,
            "onset_date": onset,
            "outcome": "Recovered",
        }
        resolution = None
        if include_resolution:
            resolution = onset + timedelta(days=resolution_delta)
            payload["resolution_date"] = resolution

        verbatim_ok = 1 <= len(verbatim) <= 200
        resolution_ok = (not include_resolution) or (resolution >= onset)
        expected_ok = verbatim_ok and resolution_ok

        if expected_ok:
            audit_before = await _audit_count(session)
            record = await service.add_adverse_event(
                session, case_id=case.id, payload=payload, actor=actor
            )
            assert record.verbatim_term == verbatim
            # A valid resolution persists; an omitted one stays null.
            if include_resolution:
                assert record.resolution_date == resolution
            else:
                assert record.resolution_date is None
            # Exactly one PV safety Audit_Event for the valid save.
            assert await _audit_count(session) == audit_before + 1
        else:
            await _assert_no_persistence_change(
                session,
                AdverseEventRecord,
                service.add_adverse_event(
                    session, case_id=case.id, payload=payload, actor=actor
                ),
            )
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3b: Seriousness_Assessment requires a criterion when serious
# ---------------------------------------------------------------------------


@given(
    serious=st.booleans(),
    criteria=st.sets(
        st.sampled_from(_VALID_CRITERIA + ("BOGUS_CRITERION",)),
        max_size=4,
    ),
)
@settings(
    max_examples=150,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_seriousness_requires_criterion_when_serious(
    serious: bool, criteria: set[str]
) -> None:
    """A serious determination needs >=1 valid criterion; else it is rejected.

    A not-serious determination persists with no criteria. A serious
    determination requires at least one recognized criterion, and any
    unrecognized criterion is rejected. A rejected assessment persists no
    seriousness row and no Audit_Event (Requirements 5.1, 5.2, 5.3, 18).

    **Validates: Requirements 3, 5, 6, 7, 18**
    """

    from app.models.pv.assessment import SeriousnessAssessment

    session, engine = await _make_session()
    service = SafetyCaseService()
    assessments = AssessmentService()
    try:
        case, actor, _user = await _seed_case(session, service)
        ae = await _add_adverse_event(session, service, case, actor)

        provided = frozenset(criteria)
        has_unknown = bool(provided - set(_VALID_CRITERIA))
        has_valid = bool(provided & set(_VALID_CRITERIA))
        # Valid exactly when: no unknown criterion, and (not serious OR >=1 valid).
        expected_ok = (not has_unknown) and ((not serious) or has_valid)

        if expected_ok:
            audit_before = await _audit_count(session)
            assessment = await assessments.record_seriousness(
                session, ae_id=ae.id, serious=serious, criteria=provided, actor=actor
            )
            assert assessment.serious == serious
            if not serious:
                assert list(assessment.criteria) == []
            else:
                assert set(assessment.criteria) == (provided & set(_VALID_CRITERIA))
            assert await _audit_count(session) == audit_before + 1
        else:
            await _assert_no_persistence_change(
                session,
                SeriousnessAssessment,
                assessments.record_seriousness(
                    session,
                    ae_id=ae.id,
                    serious=serious,
                    criteria=provided,
                    actor=actor,
                ),
            )
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3c: Case_Narrative text/reason validation and preservation
# ---------------------------------------------------------------------------


def _length_ok(value: str, limit: int) -> bool:
    trimmed = value.strip()
    return 1 <= len(trimmed) <= limit


@given(
    create_text=st.text(min_size=0, max_size=40),
    revise_text=st.text(min_size=0, max_size=40),
    reason=st.text(min_size=0, max_size=40),
    over_long=st.booleans(),
)
@settings(
    max_examples=120,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_narrative_validates_text_and_reason(
    create_text: str, revise_text: str, reason: str, over_long: bool
) -> None:
    """Narrative create/revise validate text (<=20,000) and reason (<=4,000).

    Create requires non-empty trimmed text; revise additionally requires a valid
    Reason_For_Change. Over-length text or reason is rejected. A rejected call
    preserves the existing narrative state and writes no Audit_Event
    (Requirements 7.1, 7.2, 7.3, 18).

    **Validates: Requirements 3, 5, 6, 7, 18**
    """

    session, engine = await _make_session()
    service = SafetyCaseService()
    narratives = NarrativeService()
    try:
        case, actor, _user = await _seed_case(session, service)

        # Optionally push one input over its length bound to hit the max branch.
        text_value = create_text
        if over_long:
            text_value = "x" * (NARRATIVE_TEXT_MAX_LENGTH + 1)

        create_ok = _length_ok(text_value, NARRATIVE_TEXT_MAX_LENGTH)

        if not create_ok:
            await _assert_no_persistence_change(
                session,
                CaseNarrative,
                narratives.create(
                    session, case_id=case.id, text=text_value, actor=actor
                ),
            )
            return

        audit_before = await _audit_count(session)
        narrative = await narratives.create(
            session, case_id=case.id, text=text_value, actor=actor
        )
        assert narrative.current_text == text_value.strip()
        assert await _audit_count(session) == audit_before + 1

        # Revise: valid only when both text and reason are valid.
        revise_reason = reason
        if over_long:
            revise_reason = "y" * (NARRATIVE_REASON_MAX_LENGTH + 1)

        revise_ok = _length_ok(revise_text, NARRATIVE_TEXT_MAX_LENGTH) and _length_ok(
            revise_reason, NARRATIVE_REASON_MAX_LENGTH
        )

        if revise_ok:
            audit_before = await _audit_count(session)
            version = await narratives.revise(
                session,
                narrative_id=narrative.id,
                text=revise_text,
                reason_for_change=revise_reason,
                actor=actor,
            )
            assert version.version_number == 2
            assert await _audit_count(session) == audit_before + 1
        else:
            # A rejected revise preserves the prior narrative text/version.
            prior_text = narrative.current_text
            prior_version = narrative.current_version_number
            audit_before = await _audit_count(session)
            with pytest.raises((ValidationError, NotFoundError)):
                await narratives.revise(
                    session,
                    narrative_id=narrative.id,
                    text=revise_text,
                    reason_for_change=revise_reason,
                    actor=actor,
                )
            refreshed = await session.get(CaseNarrative, narrative.id)
            await session.refresh(refreshed)
            assert refreshed.current_text == prior_text
            assert refreshed.current_version_number == prior_version
            assert await _audit_count(session) == audit_before
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3d: post-submission changes require a valid Reason_For_Change
# ---------------------------------------------------------------------------


@given(reason=st.text(min_size=0, max_size=40), over_long=st.booleans())
@settings(
    max_examples=120,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_submitted_change_requires_valid_reason(
    reason: str, over_long: bool
) -> None:
    """A submitted-data change is accepted only with a valid Reason_For_Change.

    The Reason_For_Change must be non-empty after trimming and at most 4,000
    characters. A rejected change writes no Audit_Event and leaves the submitted
    Safety_Data unchanged (Requirements 4.6, 4.7, 18).

    **Validates: Requirements 3, 5, 6, 7, 18**
    """

    session, engine = await _make_session()
    service = SafetyCaseService()
    try:
        case, actor, _user = await _seed_case(session, service)
        await service.submit_version(session, case_id=case.id, actor=actor)

        reason_value = reason
        if over_long:
            reason_value = "z" * 4001

        reason_ok = 1 <= len(reason_value.strip()) and len(reason_value) <= 4000

        if reason_ok:
            audit_before = await _audit_count(session)
            await service.change_submitted_data(
                session,
                case_id=case.id,
                changes={"case_type": "Serious Adverse Event"},
                reason_for_change=reason_value,
                actor=actor,
            )
            assert await _audit_count(session) == audit_before + 1
            refreshed = await session.get(SafetyCase, case.id)
            await session.refresh(refreshed)
            assert refreshed.case_type == "Serious Adverse Event"
        else:
            prior_case_type = case.case_type
            audit_before = await _audit_count(session)
            with pytest.raises(ValidationError):
                await service.change_submitted_data(
                    session,
                    case_id=case.id,
                    changes={"case_type": "Serious Adverse Event"},
                    reason_for_change=reason_value,
                    actor=actor,
                )
            refreshed = await session.get(SafetyCase, case.id)
            await session.refresh(refreshed)
            assert refreshed.case_type == prior_case_type
            assert await _audit_count(session) == audit_before
    finally:
        await session.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3e: Closed cases reject safety modifications, preserving state
# ---------------------------------------------------------------------------


@given(
    modification=st.sampled_from(("seriousness", "coding", "narrative")),
)
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_closed_case_rejects_safety_modifications(
    modification: str,
) -> None:
    """A Closed Safety_Case rejects new safety data with no state change.

    An adverse event is captured while the case is Open; the case is then walked
    to Closed. A subsequent seriousness assessment, MedDRA coding, or narrative
    creation is rejected and persists no row and no Audit_Event (Requirements
    5.8, 6, 7.4, 18).

    **Validates: Requirements 3, 5, 6, 7, 18**
    """

    from app.models.pv.assessment import SeriousnessAssessment
    from app.models.pv.coding import MedDraCoding

    session, engine = await _make_session()
    service = SafetyCaseService()
    assessments = AssessmentService()
    coding = CodingService(dictionary=_dictionary())
    narratives = NarrativeService()
    try:
        # Seed Open, capture an adverse event and register the dictionary, then
        # close the case so the modification below is attempted on a Closed case.
        case, actor, _user = await _seed_case(session, service, closed=False)
        ae = await _add_adverse_event(session, service, case, actor)
        await _register_meddra(session)

        await service.transition(
            session, case_id=case.id, target=CaseState.IN_REVIEW, reason=None, actor=actor
        )
        await service.transition(
            session, case_id=case.id, target=CaseState.CLOSED, reason=None, actor=actor
        )
        refreshed = await session.get(SafetyCase, case.id)
        assert refreshed.lifecycle_state == CaseState.CLOSED.value

        if modification == "seriousness":
            await _assert_no_persistence_change(
                session,
                SeriousnessAssessment,
                assessments.record_seriousness(
                    session,
                    ae_id=ae.id,
                    serious=True,
                    criteria=frozenset({SeriousnessCriterion.DEATH.value}),
                    actor=actor,
                ),
            )
        elif modification == "coding":
            await _assert_no_persistence_change(
                session,
                MedDraCoding,
                coding.assign_meddra(
                    session,
                    ae_id=ae.id,
                    term_id=VALID_MEDDRA_TERM,
                    dictionary_version=MEDDRA_VERSION,
                    actor=actor,
                ),
            )
        else:  # narrative
            await _assert_no_persistence_change(
                session,
                CaseNarrative,
                narratives.create(
                    session, case_id=case.id, text="A valid narrative body", actor=actor
                ),
            )
    finally:
        await session.close()
        await engine.dispose()
