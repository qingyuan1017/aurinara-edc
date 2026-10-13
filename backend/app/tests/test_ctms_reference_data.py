"""Focused tests for configurable CTMS dropdown reference values."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.reference_data import ReferenceCategory
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.reference_data import ReferenceValueCreate
from app.services.ctms.reference_data_service import ReferenceDataService, resolve_reference_value


def test_reference_contract_rejects_unknown_categories_and_blank_values():
    with pytest.raises(ValueError):
        ReferenceValueCreate(category="unknown", code="VALUE", label="Value")
    with pytest.raises(ValueError):
        ReferenceValueCreate(category="country", code=" ", label="United States")


@pytest.mark.asyncio
async def test_reference_values_are_unique_per_category_and_can_be_deactivated():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = User(
            email=f"reference-{uuid4()}@example.com",
            first_name="Reference",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        service = ReferenceDataService()
        country = await service.create(
            session,
            {"category": "country", "code": "us", "label": "United States", "sort_order": 10},
            actor_id=actor.id,
            correlation_id="reference-create",
        )

        assert country.code == "US"
        project_status = await service.create(
            session,
            {
                "category": "project_status",
                "code": "quality review",
                "label": "Quality Review",
                "sort_order": 30,
            },
            actor_id=actor.id,
            correlation_id="project-status-create",
        )
        assert project_status.code == "QUALITY_REVIEW"
        assert (
            await resolve_reference_value(
                session,
                ReferenceCategory.PROJECT_STATUS,
                "Quality Review",
                field="status",
            )
            == "QUALITY_REVIEW"
        )
        with pytest.raises(ValidationError, match="At least one active Project Status"):
            await service.update(
                session,
                project_status.id,
                {"active": False},
                actor_id=actor.id,
                correlation_id="project-status-disable-last",
            )
        assert (
            await resolve_reference_value(
                session, ReferenceCategory.COUNTRY, "United States", field="country"
            )
            == "US"
        )
        with pytest.raises(ValidationError):
            await resolve_reference_value(
                session, ReferenceCategory.COUNTRY, "Not configured", field="country"
            )
        with pytest.raises(ConflictError):
            await service.create(
                session,
                {"category": "country", "code": "US", "label": "Duplicate"},
                actor_id=actor.id,
                correlation_id="reference-duplicate",
            )
        updated = await service.update(
            session,
            country.id,
            {"active": False},
            actor_id=actor.id,
            correlation_id="reference-disable",
        )
        assert updated.active is False

    await engine.dispose()
