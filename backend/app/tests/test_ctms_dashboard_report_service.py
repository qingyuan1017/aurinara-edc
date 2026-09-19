"""Focused CTMS dashboard/report aggregation and scope tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import AuthorizationError
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlan,
    MonitoringPlanVersion,
)
from app.models.ctms.operational_site import ActivationAction, OperationalSite
from app.models.ctms.operational_study import (
    OperationalStudy,
    ReadinessCriterion,
    StudyOperationalMilestone,
)
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.work import OperationalContact, OperationalTask
from app.models.identity import User, UserStatus
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject, SubjectStatus
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.ctms_dashboard_service import CTMSDashboardService
from app.services.ctms_report_service import CTMSReportService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_and_reports_aggregate_operational_records_and_projected_quality_signal(db_session: AsyncSession):
    now = datetime(2026, 1, 15, tzinfo=UTC)
    actor = User(email=f"dashboard-{uuid4()}@example.test", first_name="CTMS", last_name="Reader", status=UserStatus.active)
    db_session.add(actor)
    await db_session.flush()
    study = Study(study_code=f"DASH-{uuid4()}", title="Dashboard study", created_by=actor.id)
    db_session.add(study)
    await db_session.flush()
    site = Site(study_id=study.id, site_number="001", name="Dashboard site")
    db_session.add(site)
    await db_session.flush()
    subject = Subject(study_id=study.id, site_id=site.id, study_version_id=uuid4(), subject_number="001-001", status=SubjectStatus.enrolled, created_by=actor.id)
    db_session.add(subject)
    await db_session.flush()
    db_session.add_all([
        OperationalStudy(study_id=study.id, status="Active", created_by=actor.id, correlation_id=uuid4()),
        ReadinessCriterion(study_id=study.id, name="Contracts", status="Met", required=True, created_by=actor.id, correlation_id=uuid4()),
        StudyOperationalMilestone(study_id=study.id, title="Start-up", milestone_type="start", status="Completed", created_by=actor.id, correlation_id=uuid4()),
        OperationalSite(study_id=study.id, site_id=site.id, status="Active", created_by=actor.id, correlation_id=uuid4()),
        ActivationAction(study_id=study.id, site_id=site.id, action_type="Contract", status="Completed", created_by=actor.id, correlation_id=uuid4()),
        EnrollmentTarget(study_id=study.id, site_id=site.id, target_type="Enrollment", target_quantity=3, planning_period_start=now - timedelta(days=10), planning_period_end=now + timedelta(days=10), status="Active", created_by=actor.id, correlation_id=uuid4()),
        OperationalMilestone(study_id=study.id, site_id=site.id, subject_id=subject.id, milestone_type="Enrollment", milestone_date=now - timedelta(days=1), status="Enrolled", created_by=actor.id, correlation_id=uuid4()),
        OperationalContact(study_id=study.id, site_id=site.id, name="Coordinator", status="Active", created_by=actor.id, correlation_id=uuid4()),
        OperationalTask(study_id=study.id, site_id=site.id, title="Overdue task", due_date=now - timedelta(days=2), priority="High", status="Open", created_by=actor.id, correlation_id=uuid4()),
    ])
    plan = MonitoringPlan(study_id=study.id, site_id=site.id, name="Plan", created_by=actor.id, correlation_id="plan")
    version = MonitoringPlanVersion(plan=plan, study_id=study.id, site_id=site.id, version_number=1, created_by=actor.id, correlation_id="version")
    db_session.add_all([plan, version])
    await db_session.flush()
    db_session.add(MonitoringActivity(plan_version_id=version.id, study_id=study.id, site_id=site.id, activity_type=MonitoringActivityType.ROUTINE_MONITORING.value, planned_date=now + timedelta(days=2), status=MonitoringActivityStatus.SCHEDULED.value, created_by=actor.id, correlation_id="activity"))
    db_session.add(CTMSOperationalProjection(projection_type="data_quality_signal", source_module="EDC", source_record_id=uuid4(), study_id=study.id, site_id=site.id, source_version="edc-7", source_timestamp=now - timedelta(hours=2), rule_version=1, correlation_id="quality-signal", payload_json={"signal_type": "SDV Progress", "value": 75}, payload_fingerprint="f" * 64, projected_at=now, status="current"))
    await db_session.commit()

    dashboard = await CTMSDashboardService().study_dashboard(db_session, study.id, now=now)
    assert dashboard.operational["enrollment"]["targets"]["Enrollment"] == {"target": 3, "actual": 1, "variance": 2}
    assert dashboard.operational["tasks"]["overdue"] == 1
    assert dashboard.operational["contacts"]["active"] == 1
    assert dashboard.projected_clinical[0]["read_only"] is True
    assert dashboard.projected_clinical[0]["source_module"] == "EDC"
    assert dashboard.projected_clinical[0]["freshness"] == "fresh"

    report = await CTMSReportService().task_report(db_session, study.id, priority="High", due_date="overdue", now=now)
    assert report.totals["count"] == 1
    assert report.items[0]["operational_only"] is True


@pytest.mark.asyncio
async def test_site_scoped_dashboard_excludes_other_sites(db_session: AsyncSession):
    actor = User(email=f"scope-{uuid4()}@example.test", first_name="CTMS", last_name="Reader", status=UserStatus.active)
    db_session.add(actor)
    await db_session.flush()
    study = Study(study_code=f"SCOPE-{uuid4()}", title="Scoped study", created_by=actor.id)
    db_session.add(study)
    await db_session.flush()
    site_one = Site(study_id=study.id, site_number="001", name="Allowed")
    site_two = Site(study_id=study.id, site_number="002", name="Denied")
    db_session.add_all([site_one, site_two])
    await db_session.flush()
    for site in (site_one, site_two):
        db_session.add(EnrollmentTarget(study_id=study.id, site_id=site.id, target_type="Enrollment", target_quantity=10, planning_period_start=datetime(2026, 1, 1, tzinfo=UTC), planning_period_end=datetime(2026, 12, 31, tzinfo=UTC), status="Active", created_by=actor.id, correlation_id=uuid4()))
    await db_session.commit()
    scoped_user = SimpleNamespace(authorization_scope=AuthorizationScope(grants=[PermissionGrant(permission_code="ctms.operational_data_read", study_id=study.id, site_id=site_one.id)]))

    dashboard = await CTMSDashboardService().study_dashboard(db_session, study.id, scoped_user)
    assert dashboard.operational["enrollment"]["target_count"] == 1
    with pytest.raises(AuthorizationError):
        await CTMSDashboardService().site_dashboard(db_session, site_two.id, scoped_user, study_id=study.id)
