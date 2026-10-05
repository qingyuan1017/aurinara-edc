"""PV safety dashboards and reports (task 6.2).

Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5

These example-based tests exercise the real ``PVDashboardService`` against a
deterministic in-memory SQLite database. No external service is used. They
confirm:

  - study dashboards return Safety_Case counts by lifecycle status,
    adverse-event counts by seriousness, and Regulatory_Report counts by report
    status computed from in-scope PV records (13.1);
  - reporting-compliance buckets (submitted/overdue/on-time) are mutually
    exclusive and derived from report status and the Regulatory_Clock due date
    versus the current UTC date (13.2);
  - site dashboards return only in-scope PV site metrics and zero-valued metrics
    when no records qualify (13.3);
  - all metrics are computed only from PV records within the user's
    Authorization_Scope (13.4);
  - approved EDC projections are surfaced as read-only, source-labeled fields
    and never enter a PV safety metric (13.5).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import AuthorizationError
from app.models.pv.assessment import SeriousnessAssessment
from app.models.pv.coordination import EdcAeProjection
from app.models.pv.regulatory import RegulatoryClock, RegulatoryReport
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseState,
    SafetyCase,
)
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.pv_dashboard_service import (
    READ_PERMISSION,
    SERIOUSNESS_NON_SERIOUS,
    SERIOUSNESS_SERIOUS,
    SERIOUSNESS_UNASSESSED,
    PVDashboardService,
)

STUDY = uuid4()
OTHER_STUDY = uuid4()
SITE_1 = uuid4()
SITE_2 = uuid4()

NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
TODAY = NOW.date()


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class _ScopedUser:
    """A lightweight user carrying an explicit resolved Authorization_Scope."""

    def __init__(self, scope: AuthorizationScope) -> None:
        self.authorization_scope = scope


def _study_scope(study_id=STUDY) -> AuthorizationScope:
    return AuthorizationScope(
        grants=[PermissionGrant(permission_code=READ_PERMISSION, study_id=study_id)]
    )


def _site_scope(study_id, site_id) -> AuthorizationScope:
    return AuthorizationScope(
        grants=[
            PermissionGrant(
                permission_code=READ_PERMISSION, study_id=study_id, site_id=site_id
            )
        ]
    )


async def _add_case(
    session: AsyncSession,
    *,
    study_id=STUDY,
    site_id=SITE_1,
    state: CaseState = CaseState.OPEN,
) -> SafetyCase:
    case = SafetyCase(
        case_identifier=f"CASE-{uuid4().hex[:8]}",
        study_id=study_id,
        site_id=site_id,
        subject_reference=uuid4(),
        case_type="Adverse Event",
        lifecycle_state=state.value,
    )
    session.add(case)
    await session.flush()
    return case


async def _add_ae(
    session: AsyncSession, case: SafetyCase, *, serious: bool | None = None
) -> AdverseEventRecord:
    ae = AdverseEventRecord(
        case_id=case.id,
        verbatim_term="Headache",
        onset_date=date(2024, 1, 1),
        outcome="Recovered",
    )
    session.add(ae)
    await session.flush()
    if serious is not None:
        assessment = SeriousnessAssessment(
            ae_id=ae.id,
            serious=serious,
            criteria=["death"] if serious else [],
        )
        session.add(assessment)
        await session.flush()
    return ae


async def _add_report(
    session: AsyncSession,
    case: SafetyCase,
    *,
    status: str,
    due_date: date | None,
    awareness_date: date = date(2024, 1, 1),
) -> RegulatoryReport:
    report = RegulatoryReport(
        case_id=case.id,
        report_type="Expedited",
        destination="FDA",
        status=status,
        awareness_date=awareness_date,
    )
    session.add(report)
    await session.flush()
    if due_date is not None:
        clock = RegulatoryClock(
            report_id=report.id,
            awareness_date=awareness_date,
            timeline_days=15,
            due_date=due_date,
        )
        session.add(clock)
        await session.flush()
    return report


# ---------------------------------------------------------------------------
# Study dashboard: counts by status / seriousness / report status (13.1)
# ---------------------------------------------------------------------------


class TestStudyDashboardCounts:
    async def test_case_counts_grouped_by_lifecycle_status(
        self, db_session: AsyncSession
    ) -> None:
        await _add_case(db_session, state=CaseState.OPEN)
        await _add_case(db_session, state=CaseState.OPEN)
        await _add_case(db_session, state=CaseState.CLOSED)

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )

        assert dashboard.case_counts_by_status == {
            CaseState.OPEN.value: 2,
            CaseState.CLOSED.value: 1,
        }
        assert dashboard.generated_at == NOW

    async def test_adverse_event_counts_grouped_by_seriousness(
        self, db_session: AsyncSession
    ) -> None:
        case = await _add_case(db_session)
        await _add_ae(db_session, case, serious=True)
        await _add_ae(db_session, case, serious=False)
        await _add_ae(db_session, case, serious=None)  # unassessed

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )

        assert dashboard.adverse_event_counts_by_seriousness == {
            SERIOUSNESS_SERIOUS: 1,
            SERIOUSNESS_NON_SERIOUS: 1,
            SERIOUSNESS_UNASSESSED: 1,
        }

    async def test_latest_seriousness_assessment_wins(
        self, db_session: AsyncSession
    ) -> None:
        case = await _add_case(db_session)
        ae = await _add_ae(db_session, case)
        # An earlier non-serious assessment followed by a later serious one.
        earlier = SeriousnessAssessment(
            ae_id=ae.id,
            serious=False,
            criteria=[],
            created_at=datetime(2024, 2, 1, tzinfo=UTC),
        )
        later = SeriousnessAssessment(
            ae_id=ae.id,
            serious=True,
            criteria=["hospitalization"],
            created_at=datetime(2024, 3, 1, tzinfo=UTC),
        )
        db_session.add_all([earlier, later])
        await db_session.flush()

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )

        assert dashboard.adverse_event_counts_by_seriousness == {
            SERIOUSNESS_SERIOUS: 1
        }

    async def test_report_counts_grouped_by_status(
        self, db_session: AsyncSession
    ) -> None:
        case = await _add_case(db_session)
        await _add_report(
            db_session, case, status="Submitted", due_date=TODAY - timedelta(days=1)
        )
        await _add_report(
            db_session, case, status="Pending", due_date=TODAY + timedelta(days=5)
        )
        await _add_report(
            db_session, case, status="Pending", due_date=TODAY + timedelta(days=10)
        )

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )

        assert dashboard.report_counts_by_status == {"Submitted": 1, "Pending": 2}


# ---------------------------------------------------------------------------
# Reporting-compliance buckets (13.2)
# ---------------------------------------------------------------------------


class TestReportingCompliance:
    async def test_mutually_exclusive_submitted_overdue_on_time(
        self, db_session: AsyncSession
    ) -> None:
        case = await _add_case(db_session)
        # Submitted (regardless of due date) -> submitted bucket.
        await _add_report(
            db_session, case, status="Submitted", due_date=TODAY - timedelta(days=3)
        )
        # Not submitted, due date earlier than today -> overdue.
        await _add_report(
            db_session, case, status="Pending", due_date=TODAY - timedelta(days=1)
        )
        # Not submitted, due date == today -> on time (not earlier than today).
        await _add_report(
            db_session, case, status="Pending", due_date=TODAY
        )
        # Not submitted, due date in the future -> on time.
        await _add_report(
            db_session, case, status="Rejected", due_date=TODAY + timedelta(days=7)
        )

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )
        compliance = dashboard.reporting_compliance

        assert compliance.submitted == 1
        assert compliance.overdue == 1
        assert compliance.on_time == 2
        # Buckets partition every report exactly once.
        assert compliance.total == 4

    async def test_acknowledged_and_cancelled_are_never_overdue(
        self, db_session: AsyncSession
    ) -> None:
        case = await _add_case(db_session)
        # Both have a past due date but stopped clocks -> not overdue (on time).
        await _add_report(
            db_session, case, status="Acknowledged", due_date=TODAY - timedelta(days=5)
        )
        await _add_report(
            db_session, case, status="Cancelled", due_date=TODAY - timedelta(days=5)
        )

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )
        compliance = dashboard.reporting_compliance

        assert compliance.overdue == 0
        assert compliance.submitted == 0
        assert compliance.on_time == 2


# ---------------------------------------------------------------------------
# Site dashboard scope and zero-valued metrics (13.3)
# ---------------------------------------------------------------------------


class TestSiteDashboard:
    async def test_returns_only_in_scope_site_metrics(
        self, db_session: AsyncSession
    ) -> None:
        site1 = await _add_case(db_session, site_id=SITE_1, state=CaseState.OPEN)
        await _add_ae(db_session, site1, serious=True)
        # A case at another site must not appear in the SITE_1 dashboard.
        other = await _add_case(db_session, site_id=SITE_2, state=CaseState.CLOSED)
        await _add_ae(db_session, other, serious=False)

        dashboard = await PVDashboardService().site_dashboard(
            db_session,
            SITE_1,
            _ScopedUser(_site_scope(STUDY, SITE_1)),
            study_id=STUDY,
            now=NOW,
        )

        assert dashboard.site_id == SITE_1
        assert dashboard.case_counts_by_status == {CaseState.OPEN.value: 1}
        assert dashboard.adverse_event_counts_by_seriousness == {
            SERIOUSNESS_SERIOUS: 1
        }

    async def test_zero_valued_metrics_when_no_records(
        self, db_session: AsyncSession
    ) -> None:
        dashboard = await PVDashboardService().site_dashboard(
            db_session,
            SITE_1,
            _ScopedUser(_site_scope(STUDY, SITE_1)),
            study_id=STUDY,
            now=NOW,
        )

        assert dashboard.case_counts_by_status == {}
        assert dashboard.adverse_event_counts_by_seriousness == {}
        assert dashboard.report_counts_by_status == {}
        assert dashboard.reporting_compliance.total == 0
        assert dashboard.projected_fields == []


# ---------------------------------------------------------------------------
# Authorization scope enforcement (13.4)
# ---------------------------------------------------------------------------


class TestAuthorizationScope:
    async def test_out_of_scope_study_is_denied(
        self, db_session: AsyncSession
    ) -> None:
        service = PVDashboardService()
        with pytest.raises(AuthorizationError):
            await service.study_dashboard(
                db_session, STUDY, _ScopedUser(_study_scope(OTHER_STUDY)), now=NOW
            )

    async def test_metrics_exclude_records_outside_scope(
        self, db_session: AsyncSession
    ) -> None:
        # In-scope study record.
        await _add_case(db_session, study_id=STUDY, state=CaseState.OPEN)
        # Out-of-scope study record (must not be counted).
        await _add_case(db_session, study_id=OTHER_STUDY, state=CaseState.OPEN)

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope(STUDY)), now=NOW
        )

        assert dashboard.case_counts_by_status == {CaseState.OPEN.value: 1}

    async def test_site_scope_denied_for_other_site(
        self, db_session: AsyncSession
    ) -> None:
        await _add_case(db_session, site_id=SITE_1)
        service = PVDashboardService()
        with pytest.raises(AuthorizationError):
            await service.site_dashboard(
                db_session,
                SITE_2,
                _ScopedUser(_site_scope(STUDY, SITE_1)),
                study_id=STUDY,
                now=NOW,
            )


# ---------------------------------------------------------------------------
# Read-only, source-labeled projections excluded from metrics (13.5)
# ---------------------------------------------------------------------------


class TestProjectionSeparation:
    async def test_projection_surfaced_readonly_and_excluded_from_metrics(
        self, db_session: AsyncSession
    ) -> None:
        # No PV safety cases exist; only an approved EDC projection is present.
        projection = EdcAeProjection(
            source_module="EDC",
            source_record_id=uuid4(),
            source_version="1",
            rule_version=1,
            idempotency_key=str(uuid4()),
            projected_at=NOW,
            payload_fingerprint="abc123",
            projection_status="Current",
            study_id=STUDY,
            site_id=SITE_1,
            subject_reference=uuid4(),
            verbatim_term="Nausea",
            onset_date=date(2024, 2, 1),
            seriousness="serious",
        )
        db_session.add(projection)
        await db_session.flush()

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )

        # PV safety metrics are all empty: the projection is not a PV record.
        assert dashboard.case_counts_by_status == {}
        assert dashboard.adverse_event_counts_by_seriousness == {}
        assert dashboard.report_counts_by_status == {}
        assert dashboard.reporting_compliance.total == 0

        # The projection is surfaced only as read-only, source-labeled fields.
        assert dashboard.projected_fields
        for field in dashboard.projected_fields:
            assert field.read_only is True
            assert field.ownership == "projected"
            assert field.source_module == "EDC"
            assert field.projection_id == projection.id
        surfaced = {field.field_name for field in dashboard.projected_fields}
        assert surfaced == {
            "subject_reference",
            "verbatim_term",
            "onset_date",
            "seriousness",
        }

    async def test_non_current_projection_is_not_displayed(
        self, db_session: AsyncSession
    ) -> None:
        stale = EdcAeProjection(
            source_module="EDC",
            source_record_id=uuid4(),
            source_version="1",
            rule_version=1,
            idempotency_key=str(uuid4()),
            projected_at=NOW,
            payload_fingerprint="def456",
            projection_status="Stale",
            study_id=STUDY,
            site_id=SITE_1,
            subject_reference=uuid4(),
            verbatim_term="Nausea",
            onset_date=date(2024, 2, 1),
            seriousness="serious",
        )
        db_session.add(stale)
        await db_session.flush()

        dashboard = await PVDashboardService().study_dashboard(
            db_session, STUDY, _ScopedUser(_study_scope()), now=NOW
        )

        assert dashboard.projected_fields == []
