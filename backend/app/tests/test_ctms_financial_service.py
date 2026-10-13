"""Phase 2 CTMS financial workflow and regulated-ledger invariants."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.entity_management import ManagedEntity, StudyEntityAssignment
from app.models.ctms.financial import (
    FinancialBudgetVersion,
    FinancialInvoice,
    FinancialInvoiceLine,
    PayableItem,
    PaymentAllocation,
)
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.form_data import FormInstance, FormInstanceStatus
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.financial import (
    BudgetCreate,
    BudgetLineCreate,
    BudgetVersionCreate,
    ContractVersionCreate,
    FinancialContractCreate,
    FinancialEventCalculate,
    InvoiceCreate,
    InvoiceLineCreate,
    PaymentAllocationCreate,
    PaymentCreate,
    PaymentReversalCreate,
    PaymentTermCreate,
)
from app.services.ctms.financial_service import FinancialService


async def _seed(session):
    actor = User(
        email=f"finance-{uuid4()}@example.test",
        first_name="Finance",
        last_name="Reviewer",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(study_code=f"FIN-{uuid4()}", title="Financial study", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="014", name="Memorial Research Hospital")
    session.add(site)
    await session.flush()
    return actor, study, site


@pytest.mark.asyncio
async def test_contract_event_invoice_and_partial_payment_reconciliation():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor, study, site = await _seed(session)
        service = FinancialService()
        contract = await service.create_contract(
            session,
            study.id,
            FinancialContractCreate(
                contract_number="CTA-2026-014",
                title="Site 014 clinical trial agreement",
                contract_type="clinical_trial_agreement",
                direction="payable",
                party_name=site.name,
                site_id=site.id,
                currency="usd",
            ),
            actor_id=actor.id,
            correlation_id="contract-create",
        )
        version = await service.add_version(
            session,
            study.id,
            contract.id,
            ContractVersionCreate(
                effective_from=date(2026, 1, 15),
                total_value=Decimal("425000"),
                holdback_percent=Decimal("10"),
            ),
            actor_id=actor.id,
        )
        term = await service.add_term(
            session,
            study.id,
            version.id,
            PaymentTermCreate(
                code="SCREEN",
                description="Verified screening visit",
                payment_method="visit_based",
                trigger_code="VISIT_SCREENING_VERIFIED",
                unit_rate=Decimal("1200"),
            ),
            actor_id=actor.id,
        )
        await service.execute_version(
            session,
            study.id,
            version.id,
            actor_id=actor.id,
            reason="Fully signed agreement received",
        )

        event_payload = FinancialEventCalculate(
            site_id=site.id,
            source_type="edc_visit_projection",
            trigger_code="VISIT_SCREENING_VERIFIED",
            event_date=date(2026, 2, 1),
            quantity=Decimal("3"),
            idempotency_key="edc-visits:screening:batch-001",
            evidence={"verification": "approved projection"},
        )
        event, payables, replayed = await service.calculate_event(
            session, study.id, event_payload, actor_id=actor.id
        )
        assert replayed is False
        assert len(payables) == 1
        payable = payables[0]
        assert payable.contract_term_id == term.id
        assert payable.gross_amount == Decimal("3600.00")
        assert payable.holdback_amount == Decimal("360.00")
        assert payable.net_amount == Decimal("3240.00")
        assert payable.calculation_snapshot_json["contract_version"] == 1

        replay_event, replay_payables, replayed = await service.calculate_event(
            session, study.id, event_payload, actor_id=actor.id
        )
        assert replayed is True
        assert replay_event.id == event.id
        assert [item.id for item in replay_payables] == [payable.id]

        await service.approve_payable(
            session,
            study.id,
            payable.id,
            actor_id=actor.id,
            reason="Source visit evidence reviewed",
        )
        invoice = await service.create_invoice(
            session,
            study.id,
            InvoiceCreate(
                contract_id=contract.id,
                party_name=site.name,
                invoice_number="INV-014-001",
                direction="payable",
                invoice_date=date(2026, 2, 5),
                due_date=date(2026, 3, 7),
                amount=Decimal("3240"),
                currency="USD",
                lines=[InvoiceLineCreate(payable_item_id=payable.id, amount=Decimal("3240"))],
            ),
            actor_id=actor.id,
        )
        assert payable.status == "invoiced"

        first_payment = await service.reconcile_payment(
            session,
            study.id,
            PaymentCreate(
                party_name=site.name,
                direction="payable",
                payment_date=date(2026, 2, 20),
                amount=Decimal("1000"),
                currency="USD",
                reference="ERP-SETTLEMENT-001",
                allocations=[
                    PaymentAllocationCreate(invoice_id=invoice.id, allocated_amount=Decimal("1000"))
                ],
            ),
            actor_id=actor.id,
        )
        assert first_payment.status == "settled"
        assert invoice.status == "partially_paid"

        await service.reconcile_payment(
            session,
            study.id,
            PaymentCreate(
                party_name=site.name,
                direction="payable",
                payment_date=date(2026, 2, 28),
                amount=Decimal("2240"),
                currency="USD",
                reference="ERP-SETTLEMENT-002",
                allocations=[
                    PaymentAllocationCreate(invoice_id=invoice.id, allocated_amount=Decimal("2240"))
                ],
            ),
            actor_id=actor.id,
        )
        assert invoice.status == "paid"
        overview = await service.overview(session, study.id)
        assert overview == {
            "study_id": study.id,
            "currency": "USD",
            "approved_budget": Decimal("0.00"),
            "contracted": Decimal("425000.00"),
            "earned": Decimal("3600.00"),
            "holdback": Decimal("360.00"),
            "approved": Decimal("3240.00"),
            "invoiced": Decimal("3240.00"),
            "paid": Decimal("3240.00"),
            "outstanding": Decimal("0.00"),
            "overdue": Decimal("0.00"),
        }
        reversal = await service.reverse_payment(
            session,
            study.id,
            first_payment.id,
            PaymentReversalCreate(
                payment_date=date(2026, 3, 1),
                reference="ERP-REVERSAL-001",
                reason="Settlement was returned by the bank",
            ),
            actor_id=actor.id,
        )
        assert reversal.reversal_of_id == first_payment.id
        assert first_payment.status == "reversed"
        assert invoice.status == "partially_paid"
        assert (await service.overview(session, study.id))["paid"] == Decimal("2240.00")
        assert len(list(await session.scalars(select(PayableItem)))) == 1
        assert len(list(await session.scalars(select(FinancialInvoice)))) == 1
        assert len(list(await session.scalars(select(FinancialInvoiceLine)))) == 1
        assert len(list(await session.scalars(select(PaymentAllocation)))) == 2
        assert len(list(await session.scalars(select(AuditEvent)))) >= 8

    await engine.dispose()


@pytest.mark.asyncio
async def test_budget_versions_are_approved_and_reported_as_the_study_baseline():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor, study, _ = await _seed(session)
        service = FinancialService()
        budget = await service.create_budget(
            session,
            study.id,
            BudgetCreate(
                name="Approved study baseline",
                currency="usd",
                effective_from=date(2026, 1, 1),
                lines=[
                    BudgetLineCreate(
                        category="Site costs",
                        description="Investigator grants",
                        quantity=Decimal("10"),
                        unit_cost=Decimal("12500"),
                    ),
                    BudgetLineCreate(
                        category="Central services",
                        description="Laboratory services",
                        quantity=Decimal("1"),
                        unit_cost=Decimal("75000"),
                    ),
                ],
            ),
            actor_id=actor.id,
        )
        listed = await service.list_budget_payloads(session, study.id)
        draft = listed[0]["current_version"]
        assert budget.currency == "USD"
        assert draft["total"] == Decimal("200000.00")

        await service.approve_budget_version(
            session,
            study.id,
            draft["id"],
            actor_id=actor.id,
            reason="Finance baseline approved",
        )
        overview = await service.overview(session, study.id)
        report = await service.financial_report(session, study.id)
        assert overview["approved_budget"] == Decimal("200000.00")
        assert report["budget_variance"] == Decimal("200000.00")

        revision = await service.add_budget_version(
            session,
            study.id,
            budget.id,
            BudgetVersionCreate(
                effective_from=date(2026, 7, 1),
                reason="Approved protocol amendment",
                lines=[
                    BudgetLineCreate(
                        category="Site costs",
                        description="Revised investigator grants",
                        quantity=Decimal("10"),
                        unit_cost=Decimal("21000"),
                    )
                ],
            ),
            actor_id=actor.id,
        )
        assert (await service.list_budget_payloads(session, study.id))[0]["current_version"][
            "id"
        ] == revision.id
        await service.approve_budget_version(
            session,
            study.id,
            revision.id,
            actor_id=actor.id,
            reason="Amended baseline approved",
        )
        statuses = list(
            await session.scalars(
                select(FinancialBudgetVersion.status).where(
                    FinancialBudgetVersion.budget_id == budget.id
                )
            )
        )
        assert sorted(statuses) == ["approved", "superseded"]
        assert (await service.overview(session, study.id))["approved_budget"] == Decimal(
            "210000.00"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_executed_terms_are_locked_and_caps_are_enforced():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor, study, site = await _seed(session)
        service = FinancialService()
        contract = await service.create_contract(
            session,
            study.id,
            FinancialContractCreate(
                contract_number="CTA-CAPPED",
                title="Capped CTA",
                contract_type="clinical_trial_agreement",
                direction="payable",
                party_name=site.name,
                site_id=site.id,
                currency="USD",
            ),
            actor_id=actor.id,
        )
        version = await service.add_version(
            session,
            study.id,
            contract.id,
            ContractVersionCreate(
                effective_from=date.today() - timedelta(days=1),
                total_value=Decimal("5000"),
            ),
            actor_id=actor.id,
        )
        await service.add_term(
            session,
            study.id,
            version.id,
            PaymentTermCreate(
                code="STARTUP",
                description="Startup fee",
                payment_method="fixed",
                trigger_code="SITE_ACTIVATED",
                unit_rate=Decimal("1500"),
                amount_cap=Decimal("1500"),
            ),
            actor_id=actor.id,
        )
        await service.transition_contract(
            session,
            study.id,
            contract.id,
            to_status="internal_review",
            actor_id=actor.id,
            reason="Finance review started",
        )
        await service.transition_contract(
            session,
            study.id,
            contract.id,
            to_status="approved",
            actor_id=actor.id,
            reason="Agreement approved",
        )
        await service.transition_contract(
            session,
            study.id,
            contract.id,
            to_status="executed",
            actor_id=actor.id,
            reason="Agreement executed and rate card locked",
        )
        assert version.status == "executed"
        assert version.terms_snapshot_json["terms"][0]["code"] == "STARTUP"
        with pytest.raises(ConflictError):
            await service.transition_contract(
                session,
                study.id,
                contract.id,
                to_status="approved",
                actor_id=actor.id,
                reason="Invalid backwards transition",
            )
        await service.transition_contract(
            session,
            study.id,
            contract.id,
            to_status="active",
            actor_id=actor.id,
            reason="Activate executed contract",
        )
        assert contract.status == "active"
        with pytest.raises(ConflictError):
            await service.add_term(
                session,
                study.id,
                version.id,
                PaymentTermCreate(
                    code="LATE",
                    description="Late mutable term",
                    payment_method="fixed",
                    trigger_code="SITE_ACTIVATED",
                    unit_rate=Decimal("1"),
                ),
                actor_id=actor.id,
            )
        _, payables, _ = await service.calculate_event(
            session,
            study.id,
            FinancialEventCalculate(
                site_id=site.id,
                source_type="ctms_site",
                trigger_code="SITE_ACTIVATED",
                event_date=date.today(),
                quantity=Decimal("99"),
                idempotency_key="site-activated:014",
            ),
            actor_id=actor.id,
        )
        assert payables[0].gross_amount == Decimal("1500.00")
        assert payables[0].calculation_snapshot_json["quantity"] == "1"
        with pytest.raises(ValidationError):
            await service.calculate_event(
                session,
                study.id,
                FinancialEventCalculate(
                    site_id=site.id,
                    source_type="ctms_site",
                    trigger_code="SITE_ACTIVATED",
                    event_date=date.today(),
                    idempotency_key="site-activated:014:duplicate-source",
                ),
                actor_id=actor.id,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_contract_rate_card_links_organization_and_published_edc_definitions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor, study, site = await _seed(session)
        organization = ManagedEntity(
            entity_type="participating_organization",
            code="LAB-001",
            name="Central Research Laboratory",
            created_by=actor.id,
            correlation_id=uuid4(),
        )
        session.add(organization)
        await session.flush()
        session.add(
            StudyEntityAssignment(
                study_id=study.id,
                entity_id=organization.id,
                created_by=actor.id,
                correlation_id=uuid4(),
            )
        )
        design = StudyVersion(
            study_id=study.id,
            version_number="1.0",
            status=StudyVersionStatus.published,
            published_by=actor.id,
        )
        session.add(design)
        await session.flush()
        visit_definition = VisitDefinition(
            study_version_id=design.id,
            name="Treatment Visit",
            visit_number=2,
            display_order=2,
        )
        form_definition = FormDefinition(
            study_version_id=design.id,
            name="Central Laboratory",
            form_code="LAB",
            display_order=1,
        )
        session.add_all([visit_definition, form_definition])
        await session.flush()
        subject = Subject(
            study_id=study.id,
            site_id=site.id,
            study_version_id=design.id,
            subject_number="014-001",
            created_by=actor.id,
        )
        session.add(subject)
        await session.flush()
        visit = VisitInstance(
            subject_id=subject.id,
            visit_definition_id=visit_definition.id,
            design_version_id=design.id,
            name="Treatment Visit",
            status=VisitInstanceStatus.completed,
        )
        session.add(visit)
        await session.flush()
        form = FormInstance(
            subject_id=subject.id,
            visit_instance_id=visit.id,
            form_definition_id=form_definition.id,
            design_version_id=design.id,
            status=FormInstanceStatus.submitted,
        )
        session.add(form)
        await session.flush()

        service = FinancialService()
        options = await service.configuration_options(session, study.id)
        assert options["visits"][0]["id"] == visit_definition.id
        assert options["forms"][0]["id"] == form_definition.id

        contract = await service.create_contract(
            session,
            study.id,
            FinancialContractCreate(
                contract_number="VENDOR-RATE-CARD",
                title="Configurable central lab agreement",
                contract_type="vendor_agreement",
                direction="payable",
                organization_id=organization.id,
                party_name=organization.name,
                currency="USD",
            ),
            actor_id=actor.id,
        )
        assert contract.organization_id == organization.id
        version = await service.add_version(
            session,
            study.id,
            contract.id,
            ContractVersionCreate(
                effective_from=date.today() - timedelta(days=1),
                total_value=Decimal("10000"),
            ),
            actor_id=actor.id,
        )
        visit_term = await service.add_term(
            session,
            study.id,
            version.id,
            PaymentTermCreate(
                code="VISIT",
                description="Treatment visit fee",
                payment_method="visit_based",
                trigger_code="LAB_VERIFIED",
                unit_rate=Decimal("100"),
                visit_definition_id=visit_definition.id,
                cost_category="Patient visits",
            ),
            actor_id=actor.id,
        )
        crf_term = await service.add_term(
            session,
            study.id,
            version.id,
            PaymentTermCreate(
                code="CRF",
                description="Completed laboratory CRF",
                payment_method="crf_based",
                trigger_code="LAB_VERIFIED",
                unit_rate=Decimal("25"),
                form_definition_id=form_definition.id,
                dimensions_json={"cohort": "A"},
            ),
            actor_id=actor.id,
        )
        assert visit_term.visit_definition_id == visit_definition.id
        assert crf_term.form_definition_id == form_definition.id
        await service.execute_version(
            session,
            study.id,
            version.id,
            actor_id=actor.id,
            reason="Configured rate card approved",
        )
        executable_options = await service.configuration_options(session, study.id)
        assert executable_options["payment_rules"] == [
            {
                "code": "LAB_VERIFIED",
                "label": "Completed laboratory CRF · Treatment visit fee",
                "charge_item_count": 2,
                "methods": ["crf_based", "visit_based"],
            }
        ]
        not_yet_effective = await service.configuration_options(
            session, study.id, as_of=date.today() - timedelta(days=2)
        )
        assert not_yet_effective["payment_rules"] == []
        _, payables, _ = await service.calculate_event(
            session,
            study.id,
            FinancialEventCalculate(
                site_id=site.id,
                subject_id=subject.id,
                visit_instance_id=visit.id,
                source_type="edc_form_instance",
                source_id=form.id,
                trigger_code="LAB_VERIFIED",
                event_date=date.today(),
                idempotency_key="form:lab:014-001",
                evidence={"dimensions": {"cohort": "A"}},
            ),
            actor_id=actor.id,
        )
        assert sorted(item.gross_amount for item in payables) == [
            Decimal("25.00"),
            Decimal("100.00"),
        ]
        assert all(
            item.calculation_snapshot_json["organization_id"] == str(organization.id)
            for item in payables
        )

        with pytest.raises(ValidationError):
            await service.create_contract(
                session,
                study.id,
                FinancialContractCreate(
                    contract_number="UNASSIGNED",
                    title="Invalid organization link",
                    contract_type="vendor_agreement",
                    direction="payable",
                    organization_id=uuid4(),
                    party_name="Unknown",
                    currency="USD",
                ),
                actor_id=actor.id,
            )
        with pytest.raises(ValueError):
            PaymentTermCreate(
                code="QTY",
                description="Quantity without a billing unit",
                payment_method="quantity_based",
                trigger_code="QTY_VERIFIED",
                unit_rate=Decimal("1"),
            )

    await engine.dispose()
