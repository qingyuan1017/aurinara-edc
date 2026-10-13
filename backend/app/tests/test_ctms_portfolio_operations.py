"""Portfolio operations query coverage and cross-study scope invariants."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.ctms.financial import (
    FinancialBudget,
    FinancialBudgetLine,
    FinancialBudgetVersion,
    FinancialContract,
    FinancialContractVersion,
    FinancialInvoice,
    FinancialPayment,
    PayableItem,
)
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    MonitoringFinding,
)
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User, UserStatus
from app.repositories.ctms.portfolio_repository import PortfolioRepository, PortfolioScope
from app.services.ctms.monitoring_service import MonitoringService


@pytest.mark.asyncio
async def test_portfolio_queries_are_scoped_and_keep_currency_totals_separate():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = User(
            email=f"portfolio-{uuid4()}@example.test",
            first_name="Portfolio",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        visible = Study(study_code=f"VISIBLE-{uuid4()}", title="Visible", created_by=actor.id)
        hidden = Study(study_code=f"HIDDEN-{uuid4()}", title="Hidden", created_by=actor.id)
        session.add_all([visible, hidden])
        await session.flush()
        site = Site(study_id=visible.id, site_number="001", name="Visible Site")
        session.add(site)
        await session.flush()

        now = datetime.now(UTC)
        visible_finding = MonitoringFinding(
            finding_code=f"F-{uuid4()}",
            study_id=visible.id,
            site_id=site.id,
            category="Essential documents",
            severity="Major",
            description="Document requires follow-up",
            due_date=now - timedelta(days=1),
            status="Open",
            created_by=actor.id,
            correlation_id="finding-visible",
        )
        visible_activity = MonitoringActivity(
            study_id=visible.id,
            site_id=site.id,
            plan_version_id=uuid4(),
            activity_type="Routine",
            modality="On-site",
            planned_date=now - timedelta(days=4),
            status="Scheduled",
            created_by=actor.id,
            correlation_id="portfolio-visible",
        )
        session.add_all(
            [
                visible_activity,
                MonitoringActivity(
                    study_id=hidden.id,
                    plan_version_id=uuid4(),
                    activity_type="Routine",
                    modality="Remote",
                    planned_date=now - timedelta(days=10),
                    status="Scheduled",
                    created_by=actor.id,
                    correlation_id="portfolio-hidden",
                ),
                visible_finding,
            ]
        )
        await session.flush()
        session.add(
            MonitoringActivityScheduleHistory(
                activity_id=visible_activity.id,
                previous_planned_date=now - timedelta(days=5),
                planned_date=now - timedelta(days=4),
                reason="Operational reschedule",
                changed_by=actor.id,
                correlation_id="portfolio-reschedule",
            )
        )

        usd_contract = FinancialContract(
            study_id=visible.id,
            site_id=site.id,
            contract_number="CTA-USD",
            title="USD site agreement",
            contract_type="clinical_trial_agreement",
            direction="payable",
            party_name="Visible Site",
            status="active",
            currency="USD",
            created_by=actor.id,
            correlation_id=uuid4(),
        )
        hidden_contract = FinancialContract(
            study_id=hidden.id,
            contract_number="CTA-HIDDEN",
            title="Hidden agreement",
            contract_type="vendor_agreement",
            direction="payable",
            party_name="Hidden Vendor",
            status="active",
            currency="USD",
            created_by=actor.id,
            correlation_id=uuid4(),
        )
        session.add_all([usd_contract, hidden_contract])
        await session.flush()
        session.add_all(
            [
                FinancialContractVersion(
                    contract_id=usd_contract.id,
                    version_number=1,
                    effective_from=date.today() - timedelta(days=30),
                    effective_to=date.today() + timedelta(days=20),
                    status="executed",
                    total_value=Decimal("1000"),
                    holdback_percent=Decimal("0"),
                    payment_window_days=30,
                    invoice_required=True,
                    terms_snapshot_json={},
                    created_by=actor.id,
                ),
                FinancialContractVersion(
                    contract_id=hidden_contract.id,
                    version_number=1,
                    effective_from=date.today(),
                    status="executed",
                    total_value=Decimal("9999"),
                    holdback_percent=Decimal("0"),
                    payment_window_days=30,
                    invoice_required=True,
                    terms_snapshot_json={},
                    created_by=actor.id,
                ),
            ]
        )
        budget = FinancialBudget(
            study_id=visible.id,
            name="Approved EUR Budget",
            scope="study",
            currency="EUR",
            status="approved",
            created_by=actor.id,
        )
        session.add(budget)
        await session.flush()
        budget_version = FinancialBudgetVersion(
            budget_id=budget.id,
            version_number=1,
            status="approved",
            effective_from=date.today(),
            created_by=actor.id,
        )
        session.add(budget_version)
        await session.flush()
        session.add(
            FinancialBudgetLine(
                version_id=budget_version.id,
                category="Sites",
                description="Site budget",
                quantity=Decimal("1"),
                unit_cost=Decimal("500"),
                planned_amount=Decimal("500"),
            )
        )
        session.add(
            PayableItem(
                study_id=visible.id,
                contract_id=usd_contract.id,
                contract_version_id=uuid4(),
                contract_term_id=uuid4(),
                event_id=uuid4(),
                gross_amount=Decimal("200"),
                holdback_amount=Decimal("0"),
                net_amount=Decimal("200"),
                currency="USD",
                status="approved",
                calculation_snapshot_json={},
            )
        )
        session.add(
            FinancialInvoice(
                study_id=visible.id,
                contract_id=usd_contract.id,
                party_name="Visible Site",
                invoice_number="INV-001",
                direction="payable",
                invoice_date=date.today() - timedelta(days=20),
                due_date=date.today() - timedelta(days=2),
                amount=Decimal("125"),
                currency="USD",
                status="matched",
                created_by=actor.id,
            )
        )
        session.add(
            FinancialInvoice(
                study_id=visible.id,
                contract_id=usd_contract.id,
                party_name="Visible Site",
                invoice_number="INV-DUE-SOON",
                direction="payable",
                invoice_date=date.today(),
                due_date=date.today() + timedelta(days=15),
                amount=Decimal("75"),
                currency="USD",
                status="matched",
                created_by=actor.id,
            )
        )
        session.add(
            FinancialPayment(
                study_id=visible.id,
                party_name="Visible Site",
                direction="payable",
                payment_date=date.today(),
                amount=Decimal("50"),
                currency="USD",
                reference="PAY-001",
                status="settled",
                created_by=actor.id,
            )
        )
        await session.commit()

        repository = PortfolioRepository()
        scope = PortfolioScope(
            study_ids=(visible.id,),
            study_wide_ids=(visible.id,),
            site_ids=(),
        )

        monitoring = await repository.monitoring_summary(session, scope)
        assert monitoring["total"] == 1
        assert monitoring["overdue"] == 1
        assert monitoring["open_findings"] == 1

        visits, visit_total = await repository.monitoring_activities(
            session, scope, page=1, page_size=25, overdue=True
        )
        assert visit_total == 1
        assert visits[0]["study_code"] == visible.study_code
        assert visits[0]["is_overdue"] is True
        assert visits[0]["reschedule_count"] == 1

        assigned = await MonitoringService().assign_finding(
            session,
            visible_finding.id,
            actor.id,
            reason="Portfolio triage assignment",
            actor_id=actor.id,
            correlation_id="portfolio-assignment",
        )
        assert assigned.owner_id == actor.id
        assert assigned.status == "Action Assigned"

        contracts, contract_total = await repository.contracts(session, scope, page=1, page_size=25)
        assert contract_total == 1
        assert contracts[0]["contract_number"] == "CTA-USD"
        assert contracts[0]["days_to_expiry"] == 20

        due_soon, due_soon_total = await repository.invoices(
            session, scope, page=1, page_size=25, due_within_days=30
        )
        assert due_soon_total == 1
        assert due_soon[0]["invoice_number"] == "INV-DUE-SOON"
        overdue_invoices, overdue_total = await repository.invoices(
            session, scope, page=1, page_size=25, overdue=True
        )
        assert overdue_total == 1
        assert overdue_invoices[0]["invoice_number"] == "INV-001"

        summary = await repository.financial_summary(session, scope)
        assert [row["currency"] for row in summary] == ["EUR", "USD"]
        usd = next(row for row in summary if row["currency"] == "USD")
        eur = next(row for row in summary if row["currency"] == "EUR")
        assert usd["contracted"] == Decimal("1000.00")
        assert usd["approved_payables"] == Decimal("200.00")
        assert usd["paid"] == Decimal("50.00")
        assert eur["approved_budget"] == Decimal("500.00")

        organization_report = await repository.financial_report(
            session, scope, group_by="organization"
        )
        assert len(organization_report) == 1
        assert organization_report[0]["group_by"] == "organization"
        assert organization_report[0]["contracted"] == Decimal("1000.00")

        category_report = await repository.financial_report(
            session, scope, group_by="cost_category"
        )
        assert category_report[0]["group_label"] == "Sites"
        assert category_report[0]["approved_budget"] == Decimal("500.00")

        site_scope = PortfolioScope(
            study_ids=(visible.id,),
            study_wide_ids=(),
            site_ids=(site.id,),
        )
        assert (await repository.monitoring_summary(session, site_scope))["total"] == 1
        _, site_contract_total = await repository.contracts(
            session, site_scope, page=1, page_size=25
        )
        assert site_contract_total == 1
        site_financials = await repository.financial_summary(session, site_scope)
        assert [row["currency"] for row in site_financials] == ["USD"]
        assert site_financials[0]["paid"] == Decimal("0.00")

    await engine.dispose()
