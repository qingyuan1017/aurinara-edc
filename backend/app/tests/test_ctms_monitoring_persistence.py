"""Focused persistence coverage for CTMS monitoring Phase 2 records."""

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlan,
    MonitoringPlanVersion,
    MonitoringPlanVersionStatus,
)
from app.models.identity import User, UserStatus
from app.models.site import Site
from app.models.study import Study


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _canonical_scope(session: AsyncSession) -> tuple[User, Study, Site]:
    actor = User(
        email="monitoring@example.test",
        first_name="Monitoring",
        last_name="Operator",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(study_code="MON-001", title="Monitoring study", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="001", name="Monitoring site")
    session.add(site)
    await session.flush()
    return actor, study, site


def _load_revision():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0028_create_ctms_monitoring.py"
    spec = spec_from_file_location("ctms_monitoring_revision", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_monitoring_plan_version_activity_and_schedule_history_persist(db_session: AsyncSession):
    actor, study, site = await _canonical_scope(db_session)
    plan = MonitoringPlan(
        study_id=study.id,
        site_id=site.id,
        name="Risk-based monitoring",
        created_by=actor.id,
        correlation_id="plan-1",
    )
    db_session.add(plan)
    await db_session.flush()

    version = MonitoringPlanVersion(
        plan_id=plan.id,
        study_id=study.id,
        site_id=site.id,
        version_number=1,
        objectives="Protect participant safety and data quality",
        activity_types=[MonitoringActivityType.ROUTINE_MONITORING.value],
        frequency="Every 8 weeks",
        frequency_value=8,
        frequency_unit="weeks",
        cadence="Risk-based",
        responsibilities={"cra": "assigned CRA"},
        scope={"sites": [str(site.id)]},
        completion_criteria="Report and evidence submitted",
        risk_level="High",
        monitoring_strategy="Risk-based remote and onsite review",
        thresholds={"open_queries": 5},
        created_by=actor.id,
        correlation_id="version-1",
    )
    db_session.add(version)
    await db_session.flush()
    plan.current_version_id = version.id

    activity = MonitoringActivity(
        plan_version_id=version.id,
        study_id=study.id,
        site_id=site.id,
        activity_type=MonitoringActivityType.ROUTINE_MONITORING.value,
        planned_date=datetime(2026, 2, 1, tzinfo=UTC),
        assigned_cra_id=actor.id,
        status=MonitoringActivityStatus.SCHEDULED.value,
        issue_reference="issue-17",
        escalation_reference="escalation-4",
        completion_evidence={"required": True},
        created_by=actor.id,
        correlation_id="activity-1",
    )
    db_session.add(activity)
    await db_session.flush()
    history = MonitoringActivityScheduleHistory(
        activity_id=activity.id,
        previous_planned_date=datetime(2026, 1, 15, tzinfo=UTC),
        planned_date=activity.planned_date,
        reason="CRA availability",
        changed_by=actor.id,
        correlation_id="reschedule-1",
    )
    db_session.add(history)
    await db_session.commit()

    loaded_activity = await db_session.get(MonitoringActivity, activity.id)
    loaded_history = await db_session.get(MonitoringActivityScheduleHistory, history.id)
    assert loaded_activity is not None
    assert loaded_activity.study_id == study.id
    assert loaded_activity.site_id == site.id
    assert loaded_activity.edc_visit_instance_id is None
    assert loaded_activity.issue_reference == "issue-17"
    assert loaded_history is not None
    assert loaded_history.changed_at.tzinfo is not None
    assert loaded_history.reason == "CRA availability"


@pytest.mark.asyncio
async def test_published_plan_version_rejects_direct_mutation(db_session: AsyncSession):
    actor, study, site = await _canonical_scope(db_session)
    plan = MonitoringPlan(
        study_id=study.id,
        site_id=site.id,
        name="Immutable plan",
        created_by=actor.id,
        correlation_id="plan-immutable",
    )
    version = MonitoringPlanVersion(
        plan=plan,
        study_id=study.id,
        site_id=site.id,
        version_number=1,
        objectives="Initial objectives",
        created_by=actor.id,
        correlation_id="version-immutable",
    )
    db_session.add_all([plan, version])
    await db_session.flush()
    version.status = MonitoringPlanVersionStatus.PUBLISHED.value
    version.published_by = actor.id
    version.published_at = datetime.now(UTC)
    await db_session.flush()
    await db_session.commit()

    version.objectives = "Unauthorized direct edit"
    version_id = version.id
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()

    persisted = await db_session.get(MonitoringPlanVersion, version_id)
    assert persisted is not None
    assert persisted.objectives == "Initial objectives"


def test_monitoring_revision_is_phase_gated_additive_and_has_no_clinical_tables():
    revision = _load_revision()

    assert revision.revision == "0028"
    assert revision.down_revision == "0027"
    assert set(revision._REQUIRED_EDC_TABLES) == {"users", "studies", "sites", "visit_instances"}
    assert all(table.startswith("ctms_") for table in revision._CTMS_TABLES)
    assert {
        "study_versions",
        "visit_instances",
        "form_instances",
        "field_values",
        "queries",
    }.isdisjoint(revision._CTMS_TABLES)


def test_monitoring_models_expose_indexes_and_canonical_only_visit_reference():
    activity_columns = inspect(MonitoringActivity).columns
    version_columns = inspect(MonitoringPlanVersion).columns

    assert {"study_id", "site_id", "edc_visit_instance_id", "planned_date", "assigned_cra_id"}.issubset(
        activity_columns.keys()
    )
    assert {"frequency", "risk_level", "monitoring_strategy", "thresholds", "status"}.issubset(
        version_columns.keys()
    )
    assert activity_columns["planned_date"].type.timezone
    assert activity_columns["created_at"].type.timezone
    assert not {"visit_date", "visit_window_start", "visit_window_end", "clinical_data"}.intersection(
        activity_columns.keys()
    )
