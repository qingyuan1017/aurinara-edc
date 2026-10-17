"""Focused lifecycle, scoring, and capacity coverage for portfolio completion."""

from datetime import UTC, datetime
from decimal import Decimal
from types import MethodType
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import BusinessRuleError, ValidationError
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User, UserStatus
from app.repositories.ctms.portfolio_repository import PortfolioScope
from app.schemas.ctms.portfolio_management import (
    CAPACreate,
    CAPAUpdate,
    FeasibilityCreate,
    LifecycleTransition,
    ScorecardCreate,
    WorkflowRuleCreate,
)
from app.services.ctms.portfolio_management_service import (
    DEFAULT_SCORE_WEIGHTS,
    PortfolioManagementService,
    calculate_weighted_score,
)


def test_weighted_score_renormalizes_unavailable_components():
    score, coverage = calculate_weighted_score(
        {
            "startup_timeliness": Decimal("80"),
            "enrollment_attainment": Decimal("100"),
            "monitoring_timeliness": None,
            "finding_aging": None,
            "task_timeliness": None,
            "data_quality": None,
        },
        DEFAULT_SCORE_WEIGHTS,
    )
    assert score == Decimal("92.50")
    assert coverage == Decimal("40.00")


def test_scorecard_and_workflow_validation_reject_unsafe_configuration():
    with pytest.raises(ValueError):
        ScorecardCreate(name="Invalid", weights={"data_quality": 100})
    service = PortfolioManagementService()
    with pytest.raises(ValidationError):
        service.validate_workflow(
            WorkflowRuleCreate(
                name="Unsafe",
                trigger_type="invoice_overdue",
                actions=[{"type": "execute_payment"}],
            )
        )


@pytest.mark.asyncio
async def test_feasibility_and_capa_lifecycles_require_evidence_and_reasons():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        actor = User(
            email=f"portfolio-completion-{uuid4()}@example.test",
            first_name="Portfolio",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        study = Study(study_code=f"COMP-{uuid4()}", title="Completion", created_by=actor.id)
        session.add(study)
        await session.flush()
        site = Site(study_id=study.id, site_number="001", name="Completion Site")
        session.add(site)
        await session.flush()

        service = PortfolioManagementService()
        scope = PortfolioScope(
            study_ids=(study.id,), study_wide_ids=(study.id,), site_ids=(site.id,)
        )

        async def fake_scope(self, db, user):
            return scope

        async def no_audit(self, *args, **kwargs):
            return None

        service.scope = MethodType(fake_scope, service)
        service._audit = MethodType(no_audit, service)

        assessment = await service.create_feasibility(
            session,
            actor,
            FeasibilityCreate(study_id=study.id, site_id=site.id),
            "feasibility-test",
        )
        assessment = await service.transition_feasibility(
            session,
            actor,
            assessment.id,
            LifecycleTransition(status="Questionnaire Sent", reason="Questionnaire approved"),
            "feasibility-test",
        )
        assert assessment.status == "Questionnaire Sent"
        assert assessment.sent_at is not None

        capa = await service.create_capa(
            session,
            actor,
            CAPACreate(
                study_id=study.id,
                site_id=site.id,
                source_type="monitoring_finding",
                source_id=uuid4(),
                title="Correct recurring filing issue",
                due_date=datetime(2027, 1, 1, tzinfo=UTC),
            ),
            "capa-test",
        )
        for target in ("Investigation",):
            capa = await service.transition_capa(
                session,
                actor,
                capa.id,
                LifecycleTransition(status=target, reason="Approved progression"),
                "capa-test",
            )
        with pytest.raises(BusinessRuleError):
            await service.transition_capa(
                session,
                actor,
                capa.id,
                LifecycleTransition(
                    status="Action Plan Approved", reason="Missing required root cause"
                ),
                "capa-test",
            )
        capa = await service.update_capa(
            session,
            actor,
            capa.id,
            CAPAUpdate(
                root_cause="Training procedure was incomplete",
                corrective_actions=[{"action": "Retrain staff"}],
                reason="Investigation completed",
                expected_version=capa.version,
            ),
            "capa-test",
        )
        capa = await service.transition_capa(
            session,
            actor,
            capa.id,
            LifecycleTransition(status="Action Plan Approved", reason="Plan reviewed"),
            "capa-test",
        )
        assert capa.status == "Action Plan Approved"

    await engine.dispose()
