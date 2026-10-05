"""Example-based coverage for the PV Reconciliation_Service.

Feature: pv-safety-module, Task 5.2
Validates: Requirements 10.1, 10.2, 10.3, 10.5, 10.6, 10.7

Exercises the pure ``diff`` function and the study-scoped ``run``/``resolve``
methods against an in-memory database. Reconciliation is one-way and read-only:
``run`` reads PV Safety_Cases and the approved read-only EDC adverse-event
projection and never writes EDC clinical or CTMS operational state.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.coordination import EdcAeProjection
from app.models.pv.reconciliation import (
    DiscrepancyStatus,
    ReconciliationDiscrepancy,
    ReconciliationRun,
)
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.repositories.pv.assessment_repository import AssessmentRepository
from app.services.reconciliation_service import ReconciliationService
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


def _actor(user: User) -> ActorContext:
    return ActorContext(
        user_id=user.id, request_id=str(uuid4()), correlation_id=str(uuid4())
    )


async def _seed_canonical(session: AsyncSession) -> tuple[User, Study, Site, Subject]:
    actor = User(
        email=f"pv-{uuid4()}@example.test",
        first_name="PV",
        last_name="Officer",
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


async def _seed_case_with_ae(
    session: AsyncSession,
    *,
    study,
    site,
    subject,
    actor: ActorContext,
    verbatim: str,
    onset: date,
    serious: bool | None = None,
):
    service = SafetyCaseService()
    case = await service.create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=actor,
    )
    ae = await service.add_adverse_event(
        session,
        case_id=case.id,
        payload={
            "verbatim_term": verbatim,
            "onset_date": onset.isoformat(),
            "outcome": "recovered",
        },
        actor=actor,
    )
    if serious is not None:
        repo = AssessmentRepository(session)
        await repo.add_seriousness(
            ae_id=ae.id,
            serious=serious,
            criteria=["death"] if serious else [],
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )
        await session.flush()
    return case, ae


def _add_projection(
    session: AsyncSession,
    *,
    study,
    subject_reference,
    verbatim: str,
    onset: date,
    seriousness: str | None,
    status: str = "Current",
    source_record_id=None,
) -> EdcAeProjection:
    projection = EdcAeProjection(
        source_module="EDC",
        source_record_id=source_record_id or uuid4(),
        source_version="1",
        rule_version=1,
        idempotency_key=str(uuid4()),
        projected_at=datetime.now(UTC),
        payload_fingerprint="fp",
        projection_status=status,
        study_id=study.id,
        subject_reference=subject_reference,
        verbatim_term=verbatim,
        onset_date=onset,
        seriousness=seriousness,
    )
    session.add(projection)
    return projection


async def _audit_count(session: AsyncSession, entity_type: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_type == entity_type)
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# diff — pure function (Requirements 10.1, 10.2)
# ---------------------------------------------------------------------------


def test_diff_reports_no_discrepancy_for_identical_records():
    service = ReconciliationService()
    subject = uuid4()
    edc_ref = uuid4()
    onset = date(2026, 1, 5)
    safety = [
        {
            "case_id": uuid4(),
            "subject_reference": subject,
            "verbatim_term": "Headache",
            "onset_date": onset,
            "seriousness": "not-serious",
        }
    ]
    edc = [
        {
            "edc_reference": edc_ref,
            "subject_reference": subject,
            "verbatim_term": "Headache",
            "onset_date": onset,
            "seriousness": "not-serious",
        }
    ]
    assert service.diff(safety, edc) == []


def test_diff_reports_each_differing_field_for_matched_records():
    service = ReconciliationService()
    subject = uuid4()
    edc_ref = uuid4()
    case_id = uuid4()
    safety = [
        {
            "case_id": case_id,
            "subject_reference": subject,
            "verbatim_term": "Headache",
            "onset_date": date(2026, 1, 5),
            "seriousness": "serious",
        }
    ]
    edc = [
        {
            "edc_reference": edc_ref,
            "subject_reference": subject,
            "verbatim_term": "Headache",
            "onset_date": date(2026, 1, 6),
            "seriousness": "not-serious",
        }
    ]
    result = service.diff(safety, edc)
    assert len(result) == 1
    discrepancy = result[0]
    assert discrepancy["case_id"] == case_id
    assert discrepancy["edc_reference"] == edc_ref
    # onset_date and seriousness differ; reported in canonical order.
    assert discrepancy["differing_fields"] == ["onset_date", "seriousness"]


def test_diff_reports_safety_event_missing_from_projection():
    service = ReconciliationService()
    case_id = uuid4()
    safety = [
        {
            "case_id": case_id,
            "subject_reference": uuid4(),
            "verbatim_term": "Nausea",
            "onset_date": date(2026, 2, 1),
            "seriousness": "not-serious",
        }
    ]
    result = service.diff(safety, [])
    assert len(result) == 1
    assert result[0]["case_id"] == case_id
    assert result[0]["edc_reference"] is None
    assert set(result[0]["differing_fields"]) == {
        "subject_reference",
        "verbatim_term",
        "onset_date",
        "seriousness",
    }


def test_diff_reports_projected_record_missing_from_safety():
    service = ReconciliationService()
    edc_ref = uuid4()
    edc = [
        {
            "edc_reference": edc_ref,
            "subject_reference": uuid4(),
            "verbatim_term": "Rash",
            "onset_date": date(2026, 3, 1),
            "seriousness": "serious",
        }
    ]
    result = service.diff([], edc)
    assert len(result) == 1
    assert result[0]["case_id"] is None
    assert result[0]["edc_reference"] == edc_ref


def test_diff_is_deterministic():
    service = ReconciliationService()
    subject = uuid4()
    safety = [
        {
            "case_id": uuid4(),
            "subject_reference": subject,
            "verbatim_term": "Fever",
            "onset_date": date(2026, 4, 1),
            "seriousness": "serious",
        }
    ]
    edc = [
        {
            "edc_reference": uuid4(),
            "subject_reference": subject,
            "verbatim_term": "Fever",
            "onset_date": date(2026, 4, 2),
            "seriousness": "serious",
        }
    ]
    assert service.diff(safety, edc) == service.diff(safety, edc)


# ---------------------------------------------------------------------------
# run (Requirements 10.1, 10.2, 10.3, 10.5, 10.7)
# ---------------------------------------------------------------------------


async def test_run_records_matches_and_no_discrepancy_when_aligned(db_session):
    user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(user)
    onset = date(2026, 1, 5)
    _case, _ae = await _seed_case_with_ae(
        db_session,
        study=study,
        site=site,
        subject=subject,
        actor=actor,
        verbatim="Headache",
        onset=onset,
        serious=False,
    )
    _add_projection(
        db_session,
        study=study,
        subject_reference=subject.id,
        verbatim="Headache",
        onset=onset,
        seriousness="not-serious",
    )
    await db_session.flush()

    run = await ReconciliationService().run(db_session, study_id=study.id, actor=actor)

    assert run.study_id == study.id
    assert run.match_count == 1
    assert run.discrepancy_count == 0
    discrepancies = (
        (
            await db_session.execute(
                select(ReconciliationDiscrepancy).where(
                    ReconciliationDiscrepancy.run_id == run.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert discrepancies == []
    # One run Audit_Event, no discrepancy Audit_Event.
    assert await _audit_count(db_session, "reconciliation_run") == 1
    assert await _audit_count(db_session, "reconciliation_discrepancy") == 0


async def test_run_records_discrepancy_and_audit_event(db_session):
    user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(user)
    case, _ae = await _seed_case_with_ae(
        db_session,
        study=study,
        site=site,
        subject=subject,
        actor=actor,
        verbatim="Headache",
        onset=date(2026, 1, 5),
        serious=True,
    )
    _add_projection(
        db_session,
        study=study,
        subject_reference=subject.id,
        verbatim="Headache",
        onset=date(2026, 1, 9),  # differs
        seriousness="not-serious",  # differs
    )
    await db_session.flush()

    run = await ReconciliationService().run(db_session, study_id=study.id, actor=actor)

    assert run.match_count == 0
    assert run.discrepancy_count == 1
    discrepancy = (
        (
            await db_session.execute(
                select(ReconciliationDiscrepancy).where(
                    ReconciliationDiscrepancy.run_id == run.id
                )
            )
        )
        .scalars()
        .one()
    )
    assert discrepancy.case_id == case.id
    assert discrepancy.status == DiscrepancyStatus.OPEN.value
    assert set(discrepancy.differing_fields) == {"onset_date", "seriousness"}
    # One Audit_Event on discrepancy creation (Requirement 10.7).
    assert await _audit_count(db_session, "reconciliation_discrepancy") == 1
    assert await _audit_count(db_session, "reconciliation_run") == 1


async def test_run_raises_when_projection_unavailable(db_session):
    user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(user)
    await _seed_case_with_ae(
        db_session,
        study=study,
        site=site,
        subject=subject,
        actor=actor,
        verbatim="Headache",
        onset=date(2026, 1, 5),
        serious=False,
    )
    await db_session.flush()

    with pytest.raises(ServiceUnavailableError) as error:
        await ReconciliationService().run(db_session, study_id=study.id, actor=actor)
    assert error.value.details["reason"] == "EDC_PROJECTION_UNAVAILABLE"

    # No run or discrepancy state was produced (Requirement 10.5).
    run_count = int(
        (
            await db_session.execute(select(func.count()).select_from(ReconciliationRun))
        ).scalar_one()
    )
    assert run_count == 0


async def test_run_ignores_stale_projection(db_session):
    user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(user)
    await _seed_case_with_ae(
        db_session,
        study=study,
        site=site,
        subject=subject,
        actor=actor,
        verbatim="Headache",
        onset=date(2026, 1, 5),
        serious=False,
    )
    # Only a stale projection exists -> treated as unavailable.
    _add_projection(
        db_session,
        study=study,
        subject_reference=subject.id,
        verbatim="Headache",
        onset=date(2026, 1, 5),
        seriousness="not-serious",
        status="Stale",
    )
    await db_session.flush()

    with pytest.raises(ServiceUnavailableError):
        await ReconciliationService().run(db_session, study_id=study.id, actor=actor)


# ---------------------------------------------------------------------------
# resolve (Requirement 10.7)
# ---------------------------------------------------------------------------


async def test_resolve_marks_discrepancy_resolved_with_audit(db_session):
    user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(user)
    await _seed_case_with_ae(
        db_session,
        study=study,
        site=site,
        subject=subject,
        actor=actor,
        verbatim="Headache",
        onset=date(2026, 1, 5),
        serious=True,
    )
    _add_projection(
        db_session,
        study=study,
        subject_reference=subject.id,
        verbatim="Headache",
        onset=date(2026, 1, 9),
        seriousness="not-serious",
    )
    await db_session.flush()
    run = await ReconciliationService().run(db_session, study_id=study.id, actor=actor)
    discrepancy = (
        (
            await db_session.execute(
                select(ReconciliationDiscrepancy).where(
                    ReconciliationDiscrepancy.run_id == run.id
                )
            )
        )
        .scalars()
        .one()
    )

    resolved = await ReconciliationService().resolve(
        db_session, discrepancy_id=discrepancy.id, actor=actor
    )
    assert resolved.status == DiscrepancyStatus.RESOLVED.value
    assert resolved.resolved_by == actor.user_id
    assert resolved.resolved_at is not None
    # create + resolve => two discrepancy Audit_Events.
    assert await _audit_count(db_session, "reconciliation_discrepancy") == 2


async def test_resolve_rejects_unknown_discrepancy(db_session):
    user, _study, _site, _subject = await _seed_canonical(db_session)
    actor = _actor(user)
    with pytest.raises(NotFoundError):
        await ReconciliationService().resolve(
            db_session, discrepancy_id=uuid4(), actor=actor
        )


async def test_resolve_rejects_already_resolved_discrepancy(db_session):
    user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(user)
    await _seed_case_with_ae(
        db_session,
        study=study,
        site=site,
        subject=subject,
        actor=actor,
        verbatim="Headache",
        onset=date(2026, 1, 5),
        serious=True,
    )
    _add_projection(
        db_session,
        study=study,
        subject_reference=subject.id,
        verbatim="Headache",
        onset=date(2026, 1, 9),
        seriousness="not-serious",
    )
    await db_session.flush()
    run = await ReconciliationService().run(db_session, study_id=study.id, actor=actor)
    discrepancy = (
        (
            await db_session.execute(
                select(ReconciliationDiscrepancy).where(
                    ReconciliationDiscrepancy.run_id == run.id
                )
            )
        )
        .scalars()
        .one()
    )
    await ReconciliationService().resolve(
        db_session, discrepancy_id=discrepancy.id, actor=actor
    )
    with pytest.raises(ValidationError):
        await ReconciliationService().resolve(
            db_session, discrepancy_id=discrepancy.id, actor=actor
        )
