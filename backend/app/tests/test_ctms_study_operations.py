"""Focused persistence and validation tests for expanded Study Operations."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models.ctms.coordination import CTMSOutbox
from app.models.ctms.study_operation import StudyOperationResource
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.study_operation import (
    StudyOperationCreate,
    StudyOperationResponse,
    StudyOperationUpdate,
)
from app.services.ctms.study_operation_service import StudyOperationService


@pytest.mark.asyncio
async def test_expanded_study_operation_records_are_audited_and_study_scoped():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = User(
            email=f"operations-{uuid4()}@example.test",
            first_name="Operations",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        study = Study(
            study_code=f"OPS-{uuid4()}",
            title="Operational study",
            created_by=actor.id,
        )
        other_study = Study(
            study_code=f"OTHER-{uuid4()}",
            title="Other study",
            created_by=actor.id,
        )
        session.add_all([study, other_study])
        await session.flush()
        site = Site(study_id=study.id, site_number="001", name="Study site")
        other_site = Site(study_id=other_study.id, site_number="001", name="Other site")
        session.add_all([site, other_site])
        await session.flush()

        service = StudyOperationService()
        record = await service.create(
            session,
            study.id,
            StudyOperationResource.CONTRACT,
            StudyOperationCreate(title="Site contract", site_id=site.id, status="Draft"),
            actor_id=actor.id,
            correlation_id="contract-create",
        )
        updated = await service.update(
            session,
            study.id,
            StudyOperationResource.CONTRACT,
            record.id,
            StudyOperationUpdate(status="Approved", reason="Legal approval received"),
            actor_id=actor.id,
            correlation_id="contract-approve",
        )

        assert updated.status == "Approved"
        assert StudyOperationResponse.model_validate(updated).resource_type == "contract"
        assert (
            len(
                (
                    await session.scalars(
                        select(AuditEvent).where(AuditEvent.entity_id == record.id)
                    )
                ).all()
            )
            == 2
        )
        assert (
            len(
                (
                    await session.scalars(
                        select(CTMSOutbox).where(CTMSOutbox.aggregate_id == record.id)
                    )
                ).all()
            )
            == 2
        )
        with pytest.raises(ValidationError):
            await service.create(
                session,
                study.id,
                StudyOperationResource.KRI,
                StudyOperationCreate(title="Wrong site", site_id=other_site.id),
                actor_id=actor.id,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_payment_records_require_trigger_or_request_subtype():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        actor = User(
            email=f"payment-{uuid4()}@example.test",
            first_name="Payment",
            last_name="Manager",
            status=UserStatus.active,
        )
        session.add(actor)
        await session.flush()
        study = Study(
            study_code=f"PAY-{uuid4()}",
            title="Payment study",
            created_by=actor.id,
        )
        session.add(study)
        await session.flush()

        with pytest.raises(ValidationError):
            await StudyOperationService().create(
                session,
                study.id,
                StudyOperationResource.PAYMENT,
                StudyOperationCreate(title="Invalid payment", record_subtype="Invoice"),
                actor_id=actor.id,
            )

    await engine.dispose()
