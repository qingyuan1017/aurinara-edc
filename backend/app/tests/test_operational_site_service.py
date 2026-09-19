"""Behavioral coverage for CTMS operational site workflows."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models.ctms.operational_site import ActivationActionStatus, OperationalSiteStatus
from app.models.ctms.work import OperationalContact, OperationalContactStatus
from app.models.identity import User, UserStatus
from app.models.site import Site
from app.models.study import Study
from app.services.operational_site_service import OperationalSiteService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _canonical_site(session: AsyncSession) -> tuple[User, Site]:
    actor = User(
        email="ctms-site@example.test",
        first_name="CTMS",
        last_name="Operator",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(study_code="CTMS-SITE-1", title="Site workflow", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="001", name="Canonical site")
    session.add(site)
    await session.flush()
    return actor, site


@pytest.mark.asyncio
async def test_site_profile_action_completion_and_duplicate_are_persisted(db_session: AsyncSession):
    actor, site = await _canonical_site(db_session)
    service = OperationalSiteService()

    profile = await service.create_profile(
        db_session,
        site_id=site.id,
        actor_id=actor.id,
        payload={
            "monitoring_readiness": "Ready",
            "responsible_role": "CRA",
            "planned_activation_date": datetime(2026, 1, 15, tzinfo=UTC),
        },
        correlation_id="site-profile-1",
    )
    assert profile.study_id == site.study_id
    assert profile.site_id == site.id
    assert profile.status == OperationalSiteStatus.NOT_STARTED.value

    action = await service.create_activation_action(
        db_session,
        site_id=site.id,
        actor_id=actor.id,
        payload={"action_type": "Regulatory approval"},
        correlation_id="action-1",
    )
    duplicate = await service.create_activation_action(
        db_session,
        site_id=site.id,
        actor_id=actor.id,
        payload={"action_type": "Regulatory approval"},
        correlation_id="action-2",
    )
    assert duplicate.id == action.id

    completed = await service.complete_activation_action(
        db_session,
        action,
        evidence={"reference": "evidence://approval"},
        actor_id=actor.id,
        reason="Approval verified",
        correlation_id="action-complete-1",
    )
    assert completed.status == ActivationActionStatus.COMPLETED.value
    assert completed.completed_by == actor.id
    assert completed.completed_at is not None
    assert completed.completion_evidence == "evidence://approval"


@pytest.mark.asyncio
async def test_archiving_edc_site_archives_linked_ctms_records(db_session: AsyncSession):
    actor, site = await _canonical_site(db_session)
    service = OperationalSiteService()
    profile = await service.create_profile(
        db_session, site_id=site.id, actor_id=actor.id, correlation_id="archive-profile"
    )
    action = await service.create_activation_action(
        db_session,
        site_id=site.id,
        actor_id=actor.id,
        payload={"action_type": "Site contract"},
        correlation_id="archive-action",
    )
    contact = OperationalContact(
        study_id=site.study_id,
        site_id=site.id,
        name="Site contact",
        status=OperationalContactStatus.ACTIVE.value,
        created_by=actor.id,
        updated_by=actor.id,
        correlation_id=uuid4(),
    )
    db_session.add(contact)
    await db_session.flush()

    archived = await service.on_edc_site_archived(
        db_session,
        site_id=site.id,
        actor_id=actor.id,
        reason="EDC site archived",
        correlation_id="archive-event-1",
    )
    assert archived is profile
    assert profile.status == OperationalSiteStatus.SITE_ARCHIVED.value
    assert profile.retention_state == "archived"
    assert action.status == ActivationActionStatus.ARCHIVED.value
    assert action.retention_state == "archived"
    assert contact.status == OperationalContactStatus.ARCHIVED.value
    assert contact.retention_state == "archived"


@pytest.mark.asyncio
async def test_site_status_transition_requires_reason_and_preserves_canonical_site(db_session: AsyncSession):
    actor, site = await _canonical_site(db_session)
    service = OperationalSiteService()
    profile = await service.create_profile(
        db_session, site_id=site.id, actor_id=actor.id, correlation_id="transition-profile"
    )

    with pytest.raises(ValidationError):
        await service.transition_status(
            db_session, profile, OperationalSiteStatus.IN_PROGRESS, actor_id=actor.id
        )
    await service.transition_status(
        db_session,
        profile,
        OperationalSiteStatus.IN_PROGRESS,
        reason="Activation work started",
        actor_id=actor.id,
        correlation_id="transition-1",
    )
    assert site.status.value == "active"
    assert profile.status == OperationalSiteStatus.IN_PROGRESS.value
