"""Example-based coverage for the PV Assessment_Service.

Feature: pv-safety-module, Task 3.1
Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9

Exercises the AssessmentService against an in-memory database so persistence,
validation, the serious-requires-a-criterion rule, Closed-case rejection, and
the atomic PV safety Audit_Event are covered end to end. PV references a PV
Adverse_Event_Record and never mutates the referenced EDC clinical subject.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.assessment import (
    CausalityAssessment,
    SeriousnessAssessment,
    SeriousnessCriterion,
    SeverityGrade,
)
from app.models.pv.safety_case import CaseState
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.assessment_service import AssessmentService
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
        last_name="Physician",
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


async def _seed_case_and_ae(
    session: AsyncSession,
) -> tuple[ActorContext, object, object]:
    """Return (actor context, safety case, adverse event) ready for assessment."""

    user, study, site, subject = await _seed_canonical(session)
    actor = _actor(user)
    cases = SafetyCaseService()
    case = await cases.create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=actor,
    )
    ae = await cases.add_adverse_event(
        session,
        case_id=case.id,
        payload={
            "verbatim_term": "headache",
            "onset_date": date(2026, 1, 1),
            "outcome": "Recovered",
        },
        actor=actor,
    )
    return actor, case, ae


# ---------------------------------------------------------------------------
# Seriousness (Requirements 5.1, 5.2, 5.3, 5.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_serious_with_criterion_persists_with_audit(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    assessment = await service.record_seriousness(
        db_session,
        ae_id=ae.id,
        serious=True,
        criteria=frozenset({SeriousnessCriterion.HOSPITALIZATION.value}),
        actor=actor,
    )
    assert assessment.serious is True
    assert assessment.criteria == [SeriousnessCriterion.HOSPITALIZATION.value]
    assert await _audit_count(db_session, "seriousness_assessment") == 1


@pytest.mark.asyncio
async def test_record_not_serious_persists_with_no_criteria(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    assessment = await service.record_seriousness(
        db_session, ae_id=ae.id, serious=False, criteria=frozenset(), actor=actor
    )
    assert assessment.serious is False
    assert assessment.criteria == []
    # Even a not-serious criteria set is discarded.
    other = await service.record_seriousness(
        db_session,
        ae_id=ae.id,
        serious=False,
        criteria=frozenset({SeriousnessCriterion.DEATH.value}),
        actor=actor,
    )
    assert other.criteria == []


@pytest.mark.asyncio
async def test_record_serious_without_criterion_rejected_and_preserves_state(
    db_session: AsyncSession,
):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    # Establish a prior not-serious assessment.
    await service.record_seriousness(
        db_session, ae_id=ae.id, serious=False, criteria=frozenset(), actor=actor
    )
    baseline = await _audit_count(db_session, "seriousness_assessment")

    with pytest.raises(ValidationError) as error:
        await service.record_seriousness(
            db_session, ae_id=ae.id, serious=True, criteria=frozenset(), actor=actor
        )
    assert error.value.details["reason"] == "SERIOUSNESS_CRITERION_REQUIRED"

    # No new assessment row and no new audit event were written.
    count = (
        await db_session.execute(
            select(func.count()).select_from(SeriousnessAssessment)
        )
    ).scalar_one()
    assert count == 1
    assert await _audit_count(db_session, "seriousness_assessment") == baseline


@pytest.mark.asyncio
async def test_record_seriousness_rejects_unknown_criterion(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    with pytest.raises(ValidationError) as error:
        await service.record_seriousness(
            db_session,
            ae_id=ae.id,
            serious=True,
            criteria=frozenset({"not-a-criterion"}),
            actor=actor,
        )
    assert error.value.details["field"] == "criteria"
    assert (
        await db_session.execute(select(func.count()).select_from(SeriousnessAssessment))
    ).scalar_one() == 0


# ---------------------------------------------------------------------------
# Causality (Requirements 5.4, 5.7, 5.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_causality_persists_product_category_actor_and_timestamp(
    db_session: AsyncSession,
):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    assessment = await service.record_causality(
        db_session,
        ae_id=ae.id,
        suspect_product="Study Drug A",
        category="Probable",
        actor=actor,
    )
    assert assessment.suspect_product == "Study Drug A"
    assert assessment.causality_category == "Probable"
    assert assessment.created_by == actor.user_id
    assert assessment.assessed_at is not None
    assert await _audit_count(db_session, "causality_assessment") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["", "   "])
async def test_record_causality_rejects_missing_product(
    db_session: AsyncSession, product: str
):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    with pytest.raises(ValidationError) as error:
        await service.record_causality(
            db_session,
            ae_id=ae.id,
            suspect_product=product,
            category="Probable",
            actor=actor,
        )
    assert error.value.details["field"] == "suspect_product"
    assert (
        await db_session.execute(select(func.count()).select_from(CausalityAssessment))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_record_causality_rejects_missing_adverse_event(db_session: AsyncSession):
    actor, _case, _ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    with pytest.raises(NotFoundError) as error:
        await service.record_causality(
            db_session,
            ae_id=uuid4(),
            suspect_product="Study Drug A",
            category="Probable",
            actor=actor,
        )
    assert error.value.details["entity_type"] == "adverse_event_record"
    assert (
        await db_session.execute(select(func.count()).select_from(CausalityAssessment))
    ).scalar_one() == 0


# ---------------------------------------------------------------------------
# Expectedness (Requirements 5.5, 5.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_expectedness_persists_determination(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    assessment = await service.record_expectedness(
        db_session,
        ae_id=ae.id,
        expected=False,
        actor=actor,
        reference_safety_information="Investigator Brochure v3",
    )
    assert assessment.expected is False
    assert assessment.reference_safety_information == "Investigator Brochure v3"
    assert await _audit_count(db_session, "expectedness_assessment") == 1


# ---------------------------------------------------------------------------
# Severity (Requirements 5.6, 5.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_severity_persists_grade(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    assessment = await service.record_severity(
        db_session, ae_id=ae.id, grade="Grade 3", actor=actor
    )
    assert assessment.grade == "Grade 3"
    assert await _audit_count(db_session, "severity_grade") == 1


@pytest.mark.asyncio
async def test_record_severity_rejects_missing_grade(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    with pytest.raises(ValidationError) as error:
        await service.record_severity(db_session, ae_id=ae.id, grade="  ", actor=actor)
    assert error.value.details["field"] == "grade"
    assert (
        await db_session.execute(select(func.count()).select_from(SeverityGrade))
    ).scalar_one() == 0


# ---------------------------------------------------------------------------
# Closed-case rejection (Requirement 5.8)
# ---------------------------------------------------------------------------


async def _close_case(session: AsyncSession, case, actor: ActorContext) -> None:
    cases = SafetyCaseService()
    await cases.transition(session, case_id=case.id, target=CaseState.IN_REVIEW, reason=None, actor=actor)
    await cases.transition(session, case_id=case.id, target=CaseState.CLOSED, reason=None, actor=actor)


@pytest.mark.asyncio
async def test_assessments_rejected_when_case_closed_and_state_preserved(
    db_session: AsyncSession,
):
    actor, case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    await _close_case(db_session, case, actor)
    baseline_serious = await _audit_count(db_session, "seriousness_assessment")

    with pytest.raises(ValidationError) as error:
        await service.record_seriousness(
            db_session,
            ae_id=ae.id,
            serious=True,
            criteria=frozenset({SeriousnessCriterion.DEATH.value}),
            actor=actor,
        )
    assert error.value.details["reason"] == "CASE_CLOSED"

    with pytest.raises(ValidationError):
        await service.record_causality(
            db_session, ae_id=ae.id, suspect_product="Drug", category="Probable", actor=actor
        )
    with pytest.raises(ValidationError):
        await service.record_expectedness(db_session, ae_id=ae.id, expected=True, actor=actor)
    with pytest.raises(ValidationError):
        await service.record_severity(db_session, ae_id=ae.id, grade="Grade 1", actor=actor)

    # No assessments and no assessment audit events were written.
    assert (
        await db_session.execute(select(func.count()).select_from(SeriousnessAssessment))
    ).scalar_one() == 0
    assert await _audit_count(db_session, "seriousness_assessment") == baseline_serious
    assert (
        await db_session.execute(select(func.count()).select_from(CausalityAssessment))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_reassessment_audits_prior_and_new_value(db_session: AsyncSession):
    actor, _case, ae = await _seed_case_and_ae(db_session)
    service = AssessmentService()

    await service.record_severity(db_session, ae_id=ae.id, grade="Grade 1", actor=actor)
    await service.record_severity(db_session, ae_id=ae.id, grade="Grade 3", actor=actor)

    events = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.entity_type == "severity_grade")
        )
    ).scalars().all()
    assert len(events) == 2
    recorded = {(e.action, e.old_value, e.new_value) for e in events}
    # The first assessment creates with no prior value; the second updates and
    # captures the prior value alongside the new value (Requirement 5.9).
    assert ("create", None, "Grade 1") in recorded
    assert ("update", "Grade 1", "Grade 3") in recorded
