"""Focused lifecycle and boundary coverage for CTMS study workspace completion."""

from datetime import date
from types import MethodType
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import BusinessRuleError, ConflictError
from app.models.ctms.operational_site import OperationalSite, OperationalSiteStatus
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.study_workspace import (
    CloseoutCreate,
    CloseoutItemCreate,
    CloseoutItemUpdate,
    KRICreate,
    RiskAssessmentCreate,
    RiskAssessmentVersionCreate,
    RiskItemCreate,
    TeamAssignmentCreate,
    TeamAssignmentUpdate,
    TrackingDefinitionCreate,
    TrackingDefinitionVersionCreate,
    TrackingEntryCreate,
    TrackingLogCreate,
    TransitionRequest,
)
from app.services.ctms.study_workspace_service import StudyWorkspaceService


@pytest.mark.asyncio
async def test_closeout_and_ract_lifecycles_enforce_evidence_and_immutability():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        actor = User(
            email=f"study-workspace-{uuid4()}@example.test",
            first_name="Study",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        study = Study(study_code=f"STUDY-{uuid4()}", title="Study workspace", created_by=actor.id)
        session.add(study)
        await session.flush()
        site = Site(study_id=study.id, site_number="001", name="Site 001")
        session.add(site)
        await session.flush()
        profile = OperationalSite(
            study_id=study.id,
            site_id=site.id,
            status=OperationalSiteStatus.ACTIVE.value,
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=uuid4(),
        )
        session.add(profile)
        await session.flush()

        service = StudyWorkspaceService()

        async def no_audit(self, *args, **kwargs):
            return None

        service._audit = MethodType(no_audit, service)
        summary = await service.summary(session, study.id)
        assert summary["site_count"] == 1
        assert summary["enrollment"]["operational_subjects"] == 0
        assert summary["work"]["total"] == 0
        assert summary["financials_by_currency"] == []
        health = {row["dimension"]: row for row in await service.health(session, study.id)}
        assert health["Work"]["status"] == "Unknown"
        assert health["Work"]["source_date"] is None
        assert health["Sites"]["status"] == "Green"
        assert health["Financial"]["status"] == "Unknown"
        assignment = await service.create_team(
            session,
            study.id,
            actor,
            TeamAssignmentCreate(
                user_id=actor.id,
                role="Study Manager",
                effective_from=date(2026, 1, 1),
            ),
            "team-test",
        )
        old_version = assignment.version
        assignment = await service.update_team(
            session,
            study.id,
            assignment.id,
            actor,
            TeamAssignmentUpdate(
                assignment_type="Backup",
                responsibilities="Provides study management coverage.",
                reason="Coverage model updated",
                expected_version=old_version,
            ),
            "team-test",
        )
        assert assignment.assignment_type == "Backup"
        assert assignment.version == old_version + 1
        with pytest.raises(ConflictError):
            await service.update_team(
                session,
                study.id,
                assignment.id,
                actor,
                TeamAssignmentUpdate(
                    active=False,
                    reason="Stale edit",
                    expected_version=old_version,
                ),
                "team-test",
            )
        closeout = await service.create_closeout(
            session,
            study.id,
            actor,
            CloseoutCreate(site_id=site.id, planned_date=date(2027, 1, 31)),
            "closeout-test",
        )
        item = await service.add_closeout_item(
            session,
            closeout.id,
            actor,
            CloseoutItemCreate(item_type="essential_documents", title="Final filing complete"),
            "closeout-test",
        )
        closeout = await service.transition_closeout(
            session,
            closeout.id,
            actor,
            TransitionRequest(status="In Progress", reason="Closeout started"),
            "closeout-test",
        )
        closeout = await service.transition_closeout(
            session,
            closeout.id,
            actor,
            TransitionRequest(status="Ready for Review", reason="Review requested"),
            "closeout-test",
        )
        with pytest.raises(BusinessRuleError):
            await service.transition_closeout(
                session,
                closeout.id,
                actor,
                TransitionRequest(status="Approved", reason="Attempted without evidence"),
                "closeout-test",
            )
        with pytest.raises(BusinessRuleError):
            await service.update_closeout_item(
                session,
                item.id,
                actor,
                CloseoutItemUpdate(
                    status="Completed", reason="Missing evidence", expected_version=item.version
                ),
                "closeout-test",
            )
        item = await service.update_closeout_item(
            session,
            item.id,
            actor,
            CloseoutItemUpdate(
                status="Completed",
                evidence_references=[{"attachment_id": str(uuid4())}],
                reason="Evidence verified",
                expected_version=item.version,
            ),
            "closeout-test",
        )
        assert item.completed_at is not None
        closeout = await service.transition_closeout(
            session,
            closeout.id,
            actor,
            TransitionRequest(status="Approved", reason="All requirements verified"),
            "closeout-test",
        )
        assert closeout.status == "Approved"
        closeout = await service.transition_closeout(
            session,
            closeout.id,
            actor,
            TransitionRequest(
                status="Closed",
                reason="Closeout approved",
                expected_version=closeout.version,
            ),
            "closeout-test",
        )
        assert profile.status == OperationalSiteStatus.CLOSED.value
        closeout = await service.transition_closeout(
            session,
            closeout.id,
            actor,
            TransitionRequest(
                status="In Progress",
                reason="Additional evidence requested",
                expected_version=closeout.version,
            ),
            "closeout-test",
        )
        assert profile.status == OperationalSiteStatus.IN_PROGRESS.value

        ract = await service.create_ract(
            session,
            study.id,
            actor,
            RiskAssessmentCreate(name="Initial RACT", rationale="Initial assessment"),
            "ract-test",
        )
        await service.add_risk_item(
            session,
            ract.id,
            actor,
            RiskItemCreate(
                category="Data quality",
                description="Delayed entry",
                probability=2,
                impact=3,
                detectability=2,
            ),
            "ract-test",
        )
        for status in ("Under Review", "Approved"):
            ract = await service.transition_ract(
                session,
                ract.id,
                actor,
                TransitionRequest(
                    status=status, reason=f"Move to {status}", expected_version=ract.version
                ),
                "ract-test",
            )
        with pytest.raises(BusinessRuleError):
            await service.add_risk_item(
                session,
                ract.id,
                actor,
                RiskItemCreate(
                    category="Monitoring",
                    description="Late visit",
                    probability=2,
                    impact=2,
                    detectability=2,
                ),
                "ract-test",
            )
        next_version = await service.create_ract_version(
            session,
            ract.id,
            actor,
            RiskAssessmentVersionCreate(
                rationale="Annual reassessment",
                reason="Scheduled review",
                expected_version=ract.version,
            ),
            "ract-test",
        )
        assert next_version.version_number == 2
        assert ract.status == "Draft"

        definition, definition_version = await service.create_tracking_definition(
            session,
            actor,
            TrackingDefinitionCreate(
                code="TRAINING",
                name="Training Log",
                columns=[
                    {
                        "key": "completed",
                        "label": "Completed",
                        "type": "boolean",
                        "required": True,
                    }
                ],
            ),
            "tracking-test",
        )
        await service.transition_tracking_definition(
            session,
            definition_version.id,
            actor,
            TransitionRequest(
                status="Published",
                reason="Definition approved",
                expected_version=definition.version,
            ),
        )
        log = await service.create_tracking_log(
            session,
            study.id,
            actor,
            TrackingLogCreate(
                definition_version_id=definition_version.id,
                name="Study training log",
            ),
            "tracking-test",
        )
        entry = await service.create_tracking_entry(
            session,
            log.id,
            actor,
            TrackingEntryCreate(row_key="SITE-001", values={"completed": False}),
            "tracking-test",
        )
        assert entry.values_json == {"completed": False}
        next_definition_version = await service.create_tracking_definition_version(
            session,
            definition.id,
            actor,
            TrackingDefinitionVersionCreate(
                columns=[
                    {
                        "key": "completed_at",
                        "label": "Completed at",
                        "type": "date",
                        "required": True,
                    }
                ],
                reason="Capture the completion date",
                expected_version=definition.version,
            ),
            "tracking-test",
        )
        assert next_definition_version.version_number == 2

        with pytest.raises(ValueError):
            KRICreate(
                code="BAD",
                name="Invalid thresholds",
                source_type="ctms_operational",
                amber_threshold=10,
                red_threshold=5,
                direction="above",
            )

    await engine.dispose()
