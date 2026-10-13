"""MVP coverage for plan-driven visits, reports, findings, and actions."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.models.ctms.monitoring import (
    MonitoringActivityStatus,
    MonitoringChecklistResult,
    MonitoringFindingStatus,
    MonitoringReportStatus,
)
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.monitoring import (
    MonitoringFindingResponse,
    MonitoringPlanVersionResponse,
    MonitoringReportResponse,
)
from app.services.ctms.monitoring_service import MonitoringService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _scope(session: AsyncSession) -> tuple[User, Study, Site]:
    actor = User(
        email="monitoring-mvp@example.test",
        first_name="MVP",
        last_name="CRA",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(study_code="MON-MVP", title="Monitoring MVP", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="001", name="MVP site")
    session.add(site)
    await session.flush()
    return actor, study, site


@pytest.mark.asyncio
async def test_plan_rules_generate_checklist_and_block_undocumented_completion(
    db_session: AsyncSession,
):
    actor, study, site = await _scope(db_session)
    service = MonitoringService()
    plan = await service.create_plan(
        db_session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        payload={
            "name": "Study monitoring plan",
            "version": {
                "monitoring_strategy": "Risk-based hybrid monitoring",
                "visit_rules": [
                    {
                        "visit_type": "Routine Monitoring",
                        "frequency_value": 8,
                        "frequency_unit": "weeks",
                        "allowed_modalities": ["On-site", "Remote", "Hybrid"],
                        "required_activities": [
                            "Review informed consent documentation",
                            "Review safety reporting",
                        ],
                    }
                ],
            },
        },
    )
    version = await service.publish_plan(db_session, plan, actor_id=actor.id)
    [loaded_version] = await service.list_versions(db_session, plan)
    assert loaded_version.rules[0].frequency_value == 8
    assert (
        MonitoringPlanVersionResponse.model_validate(loaded_version).rules[0].report_due_days == 10
    )

    visit = await service.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        payload={
            "activity_type": "Routine Monitoring",
            "modality": "Hybrid",
            "planned_date": datetime(2026, 10, 15, 13, 0, tzinfo=UTC),
            "assigned_cra_id": actor.id,
        },
    )
    assert visit.plan_version_id == version.id
    assert visit.visit_code.startswith("MV-2026-")
    checklist = await service.list_checklist(db_session, visit)
    assert [item.requirement for item in checklist] == [
        "Review informed consent documentation",
        "Review safety reporting",
    ]

    with pytest.raises(ConflictError, match="checklist"):
        await service.complete_activity(
            db_session,
            visit,
            evidence="evidence://mvr",
            actor_id=actor.id,
        )

    for item in checklist:
        await service.update_checklist_item(
            db_session,
            item.id,
            {
                "result": MonitoringChecklistResult.COMPLETED.value,
                "review_details": "Reviewed authorized site records",
                "observations": "No exception noted",
                "evidence_references": ["evidence://review-note"],
            },
            actor_id=actor.id,
        )
    await service.start_activity(db_session, visit, actor_id=actor.id)
    completed = await service.complete_activity(
        db_session,
        visit,
        evidence="evidence://mvr",
        actor_id=actor.id,
    )
    assert completed.status == MonitoringActivityStatus.COMPLETED.value
    assert completed.actual_start_at is not None
    assert completed.actual_end_at is not None


@pytest.mark.asyncio
async def test_report_workflow_and_finding_lifecycle_remain_independent(
    db_session: AsyncSession,
):
    actor, study, site = await _scope(db_session)
    service = MonitoringService()
    plan = await service.create_plan(
        db_session,
        study_id=study.id,
        site_id=site.id,
        actor_id=actor.id,
        payload={
            "name": "Report workflow plan",
            "activity_types": ["Routine Monitoring"],
        },
    )
    await service.publish_plan(db_session, plan, actor_id=actor.id)
    visit = await service.schedule_activity(
        db_session,
        plan=plan,
        actor_id=actor.id,
        payload={
            "activity_type": "Routine Monitoring",
            "planned_date": datetime(2026, 10, 15, tzinfo=UTC),
        },
    )
    await service.complete_activity(
        db_session,
        visit,
        evidence="evidence://visit-completion",
        actor_id=actor.id,
    )
    report = await service.create_report(
        db_session,
        visit,
        {"content": {"visit_summary": "Initial observations"}},
        actor_id=actor.id,
    )
    await service.transition_report(db_session, report.id, "submit", actor_id=actor.id)
    await service.transition_report(db_session, report.id, "start_review", actor_id=actor.id)
    await service.transition_report(
        db_session,
        report.id,
        "request_revision",
        comments="Clarify the safety review",
        actor_id=actor.id,
    )
    await service.update_report(
        db_session,
        report.id,
        {"content": {"visit_summary": "Revised", "safety_review": "Reviewed"}},
        actor_id=actor.id,
    )
    await service.transition_report(db_session, report.id, "submit", actor_id=actor.id)
    await service.transition_report(db_session, report.id, "start_review", actor_id=actor.id)
    await service.transition_report(db_session, report.id, "approve", actor_id=actor.id)

    finding = await service.create_finding(
        db_session,
        study_id=study.id,
        payload={
            "site_id": site.id,
            "visit_id": visit.id,
            "report_id": report.id,
            "category": "Informed Consent",
            "severity": "Major",
            "description": "Missing documented reconsent",
            "capa_required": True,
        },
        actor_id=actor.id,
    )
    action = await service.create_action_item(
        db_session,
        finding.id,
        {"title": "Obtain and document reconsent"},
        actor_id=actor.id,
    )
    await service.complete_action_item(
        db_session,
        action.id,
        "evidence://reconsent-verification",
        actor_id=actor.id,
    )
    finalized = await service.transition_report(
        db_session,
        report.id,
        "finalize",
        document_reference="etmf://mvr/final",
        actor_id=actor.id,
    )
    assert finalized.status == MonitoringReportStatus.FINALIZED.value
    assert finalized.controlled_snapshot is not None
    assert (
        MonitoringReportResponse.model_validate(finalized).status
        == MonitoringReportStatus.FINALIZED
    )
    assert (
        finalized.controlled_snapshot["findings"][0]["status"]
        == MonitoringFindingStatus.ACTION_ASSIGNED.value
    )
    assert finding.status == MonitoringFindingStatus.ACTION_ASSIGNED.value
    assert MonitoringFindingResponse.model_validate(finding).actions[0].status == "Completed"

    with pytest.raises(ConflictError, match="draft"):
        await service.update_report(
            db_session,
            report.id,
            {"content": {"visit_summary": "Silent rewrite"}},
            actor_id=actor.id,
        )

    await service.transition_finding(
        db_session,
        finding.id,
        MonitoringFindingStatus.IN_PROGRESS,
        reason="Corrective action underway",
        actor_id=actor.id,
    )
    await service.transition_finding(
        db_session,
        finding.id,
        MonitoringFindingStatus.PENDING_VERIFICATION,
        reason="Evidence submitted",
        actor_id=actor.id,
    )
    closed = await service.transition_finding(
        db_session,
        finding.id,
        MonitoringFindingStatus.CLOSED,
        reason="CRA verified evidence",
        resolution="Reconsent documentation verified",
        actor_id=actor.id,
    )
    assert closed.status == MonitoringFindingStatus.CLOSED.value
    assert closed.verified_by == actor.id
