"""Focused coverage for reusable CTMS entities and study assignments."""

from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.reference_data import CTMSReferenceValue
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.entity_management import ManagedEntityCreate, ManagedSiteCreate
from app.schemas.ctms.study import OperationalStudyCreate
from app.services.ctms.entity_management_service import EntityManagementService


def test_operational_study_contract_normalizes_currency_and_validates_dates():
    profile = OperationalStudyCreate(
        phase="Phase III",
        study_type="Interventional",
        main_purpose="Treatment",
        blind_method="Double blind",
        randomized=True,
        expected_subject_count=200,
        language="English",
        expected_site_count=20,
        construction_period="36 months",
        planned_start_date="2027-01-01",
        planned_end_date="2029-12-31",
        study_currency="usd",
    )

    assert profile.study_currency == "USD"
    with pytest.raises(PydanticValidationError):
        OperationalStudyCreate(
            phase="Phase III",
            study_type="Interventional",
            main_purpose="Treatment",
            blind_method="Double blind",
            randomized=True,
            expected_subject_count=200,
            language="English",
            expected_site_count=20,
            construction_period="36 months",
            planned_start_date="2027-01-01",
            planned_end_date="2029-12-31",
            study_currency="USD",
            sponsor="CTMS must not own this",
        )


def test_entity_contract_enforces_type_specific_required_fields():
    site = ManagedSiteCreate(
        name="General Hospital",
        state="New York",
        city="New York",
    )
    assert site.name == "General Hospital"
    with pytest.raises(PydanticValidationError):
        ManagedSiteCreate(
            name="General Hospital",
            state="New York",
            city="New York",
            canonical_site_id=uuid4(),
        )

    depot = ManagedEntityCreate(
        entity_type="depot",
        code="DEPOT-1",
        name="East Coast Depot",
        attributes={
            "country": "United States",
            "state": "New Jersey",
            "city": "Newark",
            "email": "depot@example.com",
            "phone": "+1 555 0100",
            "zip_code": "07101",
            "address": "100 Supply Way",
        },
    )

    assert depot.attributes["city"] == "Newark"
    with pytest.raises(PydanticValidationError):
        ManagedEntityCreate(
            entity_type="depot",
            code="DEPOT-2",
            name="Incomplete Depot",
            attributes={"country": "United States"},
        )
    with pytest.raises(PydanticValidationError):
        ManagedEntityCreate(
            entity_type="participating_organization",
            code="ORG-1",
            name="Unknown Organization",
            attributes={
                "address": "100 Main Street",
                "phone": "+1 555 0101",
                "organization_type": "",
            },
        )


@pytest.mark.asyncio
async def test_ctms_site_master_can_have_different_ids_and_numbers_in_each_study():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = User(
            email=f"site-selector-{uuid4()}@example.test",
            first_name="Site",
            last_name="Selector",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        study = Study(
            study_code=f"SELECTED-{uuid4()}",
            title="Selected study",
            sponsor="Platform sponsor",
            created_by=actor.id,
            platform_managed=True,
        )
        other_study = Study(
            study_code=f"OTHER-{uuid4()}",
            title="Other study",
            sponsor="Platform sponsor",
            created_by=actor.id,
            platform_managed=True,
        )
        session.add_all([study, other_study])
        await session.flush()
        service = EntityManagementService()

        entity = await service.create_site_entity(
            session,
            {
                "name": "General Hospital",
                "country": "US",
                "state": "New York",
                "city": "New York",
                "address": "1 Main Street",
            },
            actor_id=actor.id,
            correlation_id="site-create",
        )
        assignment = await service.assign_site_to_study(
            session,
            study.id,
            {"entity_id": entity.id, "site_number": "SITE-101"},
            actor_id=actor.id,
            correlation_id="site-assign-one",
        )
        other_assignment = await service.assign_site_to_study(
            session,
            other_study.id,
            {"entity_id": entity.id, "site_number": "2001"},
            actor_id=actor.id,
            correlation_id="site-assign-two",
        )
        with pytest.raises(ConflictError):
            await service.assign_site_to_study(
                session,
                study.id,
                {"entity_id": entity.id, "site_number": "SITE-102"},
                actor_id=actor.id,
                correlation_id="duplicate-site-assignment",
            )
        other_entity = await service.create_site_entity(
            session,
            {"name": "Other Hospital", "state": "New York", "city": "Albany"},
            actor_id=actor.id,
            correlation_id="other-site-create",
        )
        with pytest.raises(ConflictError):
            await service.assign_site_to_study(
                session,
                study.id,
                {"entity_id": other_entity.id, "site_number": "SITE-101"},
                actor_id=actor.id,
                correlation_id="duplicate-study-site-id",
            )
        canonical_site = await session.get(Site, assignment.site_id)
        other_site = await session.get(Site, other_assignment.site_id)
        synchronization_audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "site",
                AuditEvent.entity_id == assignment.site_id,
            )
        )

        assert canonical_site is not None
        assert other_site is not None
        assert entity.id not in {canonical_site.id, other_site.id}
        assert canonical_site.id != other_site.id
        assert canonical_site.study_id == study.id
        assert other_site.study_id == other_study.id
        assert canonical_site.site_number == "SITE-101"
        assert other_site.site_number == "2001"
        assert canonical_site.name == "General Hospital"
        assert canonical_site.country == "US"
        assert canonical_site.region == "New York"
        assert synchronization_audit is not None
        assert synchronization_audit.source_module == "CTMS"
        assert synchronization_audit.target_module == "PLATFORM"
        assert synchronization_audit.source_record_id == entity.id
        assert synchronization_audit.target_record_id == canonical_site.id

        updated = await service.update_entity(
            session,
            entity.id,
            {
                "name": "General Hospital Research Center",
                "attributes": {
                    "country": "US",
                    "state": "New Jersey",
                    "city": "Newark",
                    "address": "2 Research Way",
                },
            },
            actor_id=actor.id,
            correlation_id="site-update",
        )
        await session.refresh(canonical_site)
        await session.refresh(other_site)

        assert updated.id == entity.id
        assert updated.name == "General Hospital Research Center"
        assert canonical_site.name == "General Hospital Research Center"
        assert canonical_site.country == "US"
        assert canonical_site.region == "New Jersey"
        assert canonical_site.address == "2 Research Way"
        assert other_site.name == "General Hospital Research Center"
        assert other_site.site_number == "2001"

    await engine.dispose()


@pytest.mark.asyncio
async def test_configured_entities_are_reused_by_stable_id_and_not_duplicated():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = User(
            email=f"entity-{uuid4()}@example.test",
            first_name="Entity",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        study = Study(
            study_code=f"ENTITY-{uuid4()}",
            title="Platform study",
            sponsor="Platform sponsor",
            created_by=actor.id,
            platform_managed=True,
        )
        session.add(study)
        await session.flush()

        service = EntityManagementService()
        session.add(
            CTMSReferenceValue(
                category="participating_organization_type",
                code="SPONSOR",
                label="Sponsor",
                sort_order=10,
            )
        )
        await session.flush()
        country = await service.create_entity(
            session,
            {"entity_type": "country", "code": "us", "name": "United States"},
            actor_id=actor.id,
            correlation_id="entity-create",
        )
        assignment = await service.assign_to_study(
            session,
            study.id,
            {"entity_id": country.id},
            actor_id=actor.id,
            correlation_id="entity-assign",
        )
        staff = await service.create_entity(
            session,
            {
                "entity_type": "staff",
                "code": "JANE-COORDINATOR",
                "name": "Jane Coordinator",
                "attributes": {
                    "first_name": "Jane",
                    "last_name": "Coordinator",
                    "email": "jane@example.com",
                },
            },
            actor_id=actor.id,
            correlation_id="staff-create",
        )
        organization = await service.create_entity(
            session,
            {
                "entity_type": "participating_organization",
                "code": "SPONSOR-ONE",
                "name": "Sponsor One",
                "attributes": {
                    "address": "1 Sponsor Plaza",
                    "phone": "+1 555 0102",
                    "organization_type": "Sponsor",
                    "primary_contact_id": str(staff.id),
                },
            },
            actor_id=actor.id,
            correlation_id="organization-create",
        )
        product = await service.create_entity(
            session,
            {
                "entity_type": "investigational_product",
                "code": "CMP-001",
                "name": "CMP-001",
                "attributes": {
                    "generic_name": "Compound One",
                    "formulation": "Tablet",
                    "specification": "10 mg",
                    "pharmaceutical_company_id": str(organization.id),
                },
            },
            actor_id=actor.id,
            correlation_id="product-create",
        )

        assert country.code == "US"
        assert organization.attributes["organization_type"] == "SPONSOR"
        assert product.attributes["pharmaceutical_company_id"] == str(organization.id)
        assert assignment.entity_id == country.id
        assert assignment.study_id == study.id
        with pytest.raises(ValidationError):
            await service.create_entity(
                session,
                {
                    "entity_type": "participating_organization",
                    "code": "ORG-INVALID",
                    "name": "Invalid Organization",
                    "attributes": {
                        "address": "2 Sponsor Plaza",
                        "phone": "+1 555 0103",
                        "organization_type": "Not Configured",
                    },
                },
                actor_id=actor.id,
                correlation_id="invalid-organization-create",
            )
        with pytest.raises(ValidationError):
            await service.create_entity(
                session,
                {
                    "entity_type": "investigational_product",
                    "code": "CMP-INVALID",
                    "name": "Invalid Product",
                    "attributes": {
                        "generic_name": "Invalid",
                        "formulation": "Tablet",
                        "specification": "20 mg",
                        "pharmaceutical_company_id": str(staff.id),
                    },
                },
                actor_id=actor.id,
                correlation_id="invalid-product-create",
            )
        with pytest.raises(ConflictError):
            await service.assign_to_study(
                session,
                study.id,
                {"entity_id": country.id},
                actor_id=actor.id,
                correlation_id="entity-assign-duplicate",
            )

    await engine.dispose()
