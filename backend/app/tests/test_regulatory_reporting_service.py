"""Example-based coverage for the PV Regulatory_Reporting_Service.

Feature: pv-safety-module, Task 4.1
Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9

Exercises reportability evaluation, the pure ``compute_clock``/``is_overdue``
functions, the report status state machine, and Submitted-report submission
metadata against an in-memory database. Reports reference the PV-owned
``pv_safety_cases`` root and never mutate the referenced EDC clinical subject.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext, ReportStatus
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.regulatory import (
    RegulatoryClock,
    RegulatoryReport,
    ReportabilityRule,
)
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.regulatory_reporting_service import RegulatoryReportingService
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


async def _seed_case(
    session: AsyncSession,
) -> tuple[ActorContext, Study, object]:
    user, study, site, subject = await _seed_canonical(session)
    actor = _actor(user)
    case = await SafetyCaseService().create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        payload={},
        actor=actor,
    )
    return actor, study, case


async def _add_rule(
    session: AsyncSession,
    *,
    study_id,
    report_type: str,
    destination: str,
    timeline_days: int,
    active: bool = True,
) -> ReportabilityRule:
    rule = ReportabilityRule(
        study_id=study_id,
        name=f"{report_type}->{destination}",
        report_type=report_type,
        destination=destination,
        timeline_days=timeline_days,
        active=active,
    )
    session.add(rule)
    await session.flush()
    return rule


async def _audit_count(session: AsyncSession, entity_type: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_type == entity_type
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# compute_clock (Requirement 8.3) — pure function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("awareness", "timeline_days", "expected"),
    [
        (date(2026, 1, 1), 1, date(2026, 1, 2)),
        (date(2026, 1, 1), 15, date(2026, 1, 16)),
        (date(2026, 1, 1), 90, date(2026, 4, 1)),
        (date(2026, 2, 28), 1, date(2026, 3, 1)),  # non-leap year rollover
    ],
)
def test_compute_clock_adds_whole_days_from_day_zero(awareness, timeline_days, expected):
    service = RegulatoryReportingService()
    assert service.compute_clock(awareness, timeline_days) == expected


@pytest.mark.parametrize("timeline_days", [0, 91, -1, 200])
def test_compute_clock_rejects_out_of_range_timeline(timeline_days):
    service = RegulatoryReportingService()
    with pytest.raises(ValidationError) as error:
        service.compute_clock(date(2026, 1, 1), timeline_days)
    assert error.value.details["reason"] == "INVALID_TIMELINE_DAYS"


def test_compute_clock_rejects_boolean_timeline():
    service = RegulatoryReportingService()
    with pytest.raises(ValidationError):
        service.compute_clock(date(2026, 1, 1), True)


# ---------------------------------------------------------------------------
# is_overdue (Requirement 8.6) — pure predicate
# ---------------------------------------------------------------------------


def test_is_overdue_true_when_past_due_and_status_open():
    service = RegulatoryReportingService()
    due = date(2026, 1, 10)
    assert service.is_overdue(due, ReportStatus.PENDING, date(2026, 1, 11)) is True
    assert service.is_overdue(due, ReportStatus.REJECTED, date(2026, 1, 11)) is True


def test_is_overdue_false_on_or_before_due_date():
    service = RegulatoryReportingService()
    due = date(2026, 1, 10)
    assert service.is_overdue(due, ReportStatus.PENDING, date(2026, 1, 10)) is False
    assert service.is_overdue(due, ReportStatus.PENDING, date(2026, 1, 9)) is False


@pytest.mark.parametrize(
    "status",
    [ReportStatus.SUBMITTED, ReportStatus.ACKNOWLEDGED, ReportStatus.CANCELLED],
)
def test_is_overdue_false_for_clock_stopped_statuses(status):
    service = RegulatoryReportingService()
    # Even well past the due date, a clock-stopped status is never overdue.
    assert service.is_overdue(date(2026, 1, 1), status, date(2026, 12, 31)) is False


# ---------------------------------------------------------------------------
# evaluate_reportability (Requirements 8.1, 8.2, 8.3, 8.4, 8.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_creates_one_pending_report_per_matched_rule(db_session):
    actor, study, case = await _seed_case(db_session)
    await _add_rule(
        db_session, study_id=study.id, report_type="15-day", destination="FDA", timeline_days=15
    )
    await _add_rule(
        db_session, study_id=study.id, report_type="7-day", destination="EMA", timeline_days=7
    )
    service = RegulatoryReportingService()

    awareness = date(2026, 3, 1)
    reports = await service.evaluate_reportability(
        db_session, case_id=case.id, awareness_date=awareness, actor=actor
    )

    assert len(reports) == 2
    assert all(r.status == ReportStatus.PENDING.value for r in reports)
    by_type = {r.report_type: r for r in reports}
    assert by_type["15-day"].destination == "FDA"
    assert by_type["7-day"].destination == "EMA"

    # Each report has a clock with the computed due date (day zero = awareness).
    clocks = (
        await db_session.execute(select(RegulatoryClock))
    ).scalars().all()
    due_by_report = {c.report_id: c.due_date for c in clocks}
    assert due_by_report[by_type["15-day"].id] == awareness + timedelta(days=15)
    assert due_by_report[by_type["7-day"].id] == awareness + timedelta(days=7)

    # One PV safety Audit_Event per created report (Requirement 8.9).
    assert await _audit_count(db_session, "regulatory_report") == 2


@pytest.mark.asyncio
async def test_evaluate_single_matched_rule_creates_single_report(db_session):
    actor, study, case = await _seed_case(db_session)
    await _add_rule(
        db_session, study_id=study.id, report_type="15-day", destination="FDA", timeline_days=15
    )
    # An inactive rule must not match.
    await _add_rule(
        db_session,
        study_id=study.id,
        report_type="inactive",
        destination="X",
        timeline_days=30,
        active=False,
    )
    service = RegulatoryReportingService()

    reports = await service.evaluate_reportability(
        db_session, case_id=case.id, awareness_date=date(2026, 3, 1), actor=actor
    )
    assert len(reports) == 1
    assert reports[0].report_type == "15-day"


@pytest.mark.asyncio
async def test_evaluate_without_awareness_date_creates_no_report(db_session):
    actor, study, case = await _seed_case(db_session)
    await _add_rule(
        db_session, study_id=study.id, report_type="15-day", destination="FDA", timeline_days=15
    )
    service = RegulatoryReportingService()

    with pytest.raises(ValidationError) as error:
        await service.evaluate_reportability(
            db_session, case_id=case.id, awareness_date=None, actor=actor
        )
    assert error.value.details["reason"] == "AWARENESS_DATE_REQUIRED"

    assert (
        await db_session.execute(select(func.count()).select_from(RegulatoryReport))
    ).scalar_one() == 0
    assert await _audit_count(db_session, "regulatory_report") == 0


@pytest.mark.asyncio
async def test_evaluate_rejects_missing_case(db_session):
    user, _study, _site, _subject = await _seed_canonical(db_session)
    service = RegulatoryReportingService()
    with pytest.raises(NotFoundError):
        await service.evaluate_reportability(
            db_session, case_id=uuid4(), awareness_date=date(2026, 1, 1), actor=_actor(user)
        )


# ---------------------------------------------------------------------------
# Submission (Requirements 8.7, 8.8, 8.9)
# ---------------------------------------------------------------------------


async def _one_report(db_session, service, actor, study, case) -> RegulatoryReport:
    await _add_rule(
        db_session, study_id=study.id, report_type="15-day", destination="FDA", timeline_days=15
    )
    reports = await service.evaluate_reportability(
        db_session, case_id=case.id, awareness_date=date(2026, 3, 1), actor=actor
    )
    return reports[0]


@pytest.mark.asyncio
async def test_submit_records_actor_timestamp_and_reference(db_session):
    actor, study, case = await _seed_case(db_session)
    service = RegulatoryReportingService()
    report = await _one_report(db_session, service, actor, study, case)

    submitted = await service.submit(
        db_session, report_id=report.id, e2b_message_ref="E2B-REF-001", actor=actor
    )
    assert submitted.status == ReportStatus.SUBMITTED.value
    assert submitted.submitted_by == actor.user_id
    assert submitted.submitted_at is not None
    assert submitted.e2b_message_ref == "E2B-REF-001"
    # create + submit audit events for this report.
    assert await _audit_count(db_session, "regulatory_report") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["", "   "])
async def test_submit_without_reference_rejected_and_status_preserved(db_session, reference):
    actor, study, case = await _seed_case(db_session)
    service = RegulatoryReportingService()
    report = await _one_report(db_session, service, actor, study, case)
    baseline_audit = await _audit_count(db_session, "regulatory_report")

    with pytest.raises(ValidationError) as error:
        await service.submit(
            db_session, report_id=report.id, e2b_message_ref=reference, actor=actor
        )
    assert error.value.details["reason"] == "E2B_MESSAGE_REFERENCE_REQUIRED"

    refreshed = (
        await db_session.execute(
            select(RegulatoryReport).where(RegulatoryReport.id == report.id)
        )
    ).scalar_one()
    assert refreshed.status == ReportStatus.PENDING.value
    assert refreshed.submitted_at is None
    assert await _audit_count(db_session, "regulatory_report") == baseline_audit


# ---------------------------------------------------------------------------
# State machine (Requirement 8.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_allows_pending_to_cancelled(db_session):
    actor, study, case = await _seed_case(db_session)
    service = RegulatoryReportingService()
    report = await _one_report(db_session, service, actor, study, case)

    updated = await service.transition(
        db_session, report_id=report.id, target=ReportStatus.CANCELLED, actor=actor
    )
    assert updated.status == ReportStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_transition_submitted_to_acknowledged_and_rejected_then_pending(db_session):
    actor, study, case = await _seed_case(db_session)
    service = RegulatoryReportingService()
    report = await _one_report(db_session, service, actor, study, case)

    await service.submit(
        db_session, report_id=report.id, e2b_message_ref="ref", actor=actor
    )
    rejected = await service.transition(
        db_session, report_id=report.id, target=ReportStatus.REJECTED, actor=actor
    )
    assert rejected.status == ReportStatus.REJECTED.value

    # Rejected -> Pending is permitted.
    reopened = await service.transition(
        db_session, report_id=report.id, target=ReportStatus.PENDING, actor=actor
    )
    assert reopened.status == ReportStatus.PENDING.value


@pytest.mark.asyncio
async def test_transition_to_submitted_requires_submit(db_session):
    actor, study, case = await _seed_case(db_session)
    service = RegulatoryReportingService()
    report = await _one_report(db_session, service, actor, study, case)

    with pytest.raises(ValidationError) as error:
        await service.transition(
            db_session, report_id=report.id, target=ReportStatus.SUBMITTED, actor=actor
        )
    assert error.value.details["reason"] == "SUBMIT_REQUIRES_E2B_REFERENCE"


@pytest.mark.asyncio
async def test_invalid_transition_rejected_without_change(db_session):
    actor, study, case = await _seed_case(db_session)
    service = RegulatoryReportingService()
    report = await _one_report(db_session, service, actor, study, case)
    baseline_audit = await _audit_count(db_session, "regulatory_report")

    # Pending -> Acknowledged is not permitted.
    with pytest.raises(ValidationError) as error:
        await service.transition(
            db_session, report_id=report.id, target=ReportStatus.ACKNOWLEDGED, actor=actor
        )
    assert error.value.details["reason"] == "TRANSITION_NOT_PERMITTED"

    unchanged = (
        await db_session.execute(
            select(RegulatoryReport).where(RegulatoryReport.id == report.id)
        )
    ).scalar_one()
    assert unchanged.status == ReportStatus.PENDING.value
    assert await _audit_count(db_session, "regulatory_report") == baseline_audit
