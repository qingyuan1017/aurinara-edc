"""Focused tests for CTMS Work_Management_Service.

**Validates: Requirements 7.1-7.11, 12.1-12.5, 14.1, 14.6**
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import BusinessRuleError, ConflictError
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.models.ctms.work import (
    EscalationStatus,
    OperationalContactStatus,
    OperationalTask,
    OperationalTaskStatus,
    TaskDependency,
)
from app.models.identity import User, UserStatus
from app.models.notification import Notification
from app.models.query import Query, QueryStatus, QueryTargetType
from app.models.site import Site
from app.models.study import Study
from app.services.work_management_service import WorkManagementService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _context(session: AsyncSession) -> tuple[User, User, Study, Site, Query]:
    actor = User(
        email=f"actor-{uuid4()}@example.test",
        first_name="CTMS",
        last_name="Actor",
        status=UserStatus.active,
    )
    owner = User(
        email=f"owner-{uuid4()}@example.test",
        first_name="Task",
        last_name="Owner",
        status=UserStatus.active,
    )
    session.add_all([actor, owner])
    await session.flush()
    study = Study(study_code=f"WORK-{uuid4()}", title="Work study", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number=f"{uuid4().int % 100000:05d}", name="Work site")
    query = Query(
        study_id=study.id,
        site_id=None,
        target_type=QueryTargetType.subject.value,
        target_id=uuid4(),
        text="clinical query text must never be copied",
        status=QueryStatus.open,
        created_by=actor.id,
    )
    session.add_all([site, query])
    await session.flush()
    return actor, owner, study, site, query


async def _task(
    service: WorkManagementService,
    session: AsyncSession,
    actor: User,
    owner: User,
    study: Study,
    site: Site,
    title: str,
) -> OperationalTask:
    return await service.create_task(
        session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        title=title,
        owner_id=owner.id,
        correlation_id=f"corr-{title}",
    )


@pytest.mark.asyncio
async def test_query_follow_up_is_operational_and_does_not_mutate_edc_query(db_session: AsyncSession):
    actor, owner, _study, _site, query = await _context(db_session)
    service = WorkManagementService()
    original = (query.status, query.text)

    task = await service.create_query_follow_up(
        db_session,
        query_id=query.id,
        actor_id=actor.id,
        owner_id=owner.id,
        approved_summary="Approved operational summary",
        correlation_id="follow-up-correlation",
    )
    await db_session.commit()

    assert task.query_id == query.id
    assert task.query_summary == "Approved operational summary"
    assert task.description == "Operational follow-up for an EDC Query"
    assert "clinical query text" not in repr(task)
    assert (query.status, query.text) == original
    assert not hasattr(task, "clinical_data")
    notifications = (await db_session.execute(select(Notification))).scalars().all()
    assert any(item.type == "ctms_task_assigned" and item.user_id == owner.id for item in notifications)


@pytest.mark.asyncio
async def test_task_lifecycle_records_history_audit_outbox_and_rejects_inactive_assignment(
    db_session: AsyncSession,
):
    actor, owner, study, site, _query = await _context(db_session)
    inactive = User(
        email=f"inactive-{uuid4()}@example.test",
        first_name="Inactive",
        last_name="Owner",
        status=UserStatus.inactive,
    )
    db_session.add(inactive)
    await db_session.flush()
    service = WorkManagementService()

    with pytest.raises(ConflictError, match="inactive"):
        await service.create_task(
            db_session,
            actor_id=actor.id,
            study_id=study.id,
            site_id=site.id,
            title="No inactive owner",
            owner_id=inactive.id,
        )
    assert not (await db_session.execute(select(OperationalTask))).scalars().all()

    task = await _task(service, db_session, actor, owner, study, site, "Lifecycle")
    await service.transition_task_status(
        db_session, task, OperationalTaskStatus.IN_PROGRESS, actor.id, reason="Started work"
    )
    await service.transition_task_status(
        db_session, task, OperationalTaskStatus.COMPLETED, actor.id, reason="Finished work"
    )
    await db_session.commit()

    history = (
        await db_session.execute(
            select(CTMSStatusHistory).where(
                CTMSStatusHistory.entity_type == "operational_task",
                CTMSStatusHistory.entity_id == task.id,
            )
        )
    ).scalars().all()
    audits = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.entity_id == task.id)
        )
    ).scalars().all()
    outbox = (
        await db_session.execute(
            select(CTMSOutbox).where(CTMSOutbox.aggregate_id == task.id)
        )
    ).scalars().all()
    assert task.status == OperationalTaskStatus.COMPLETED.value
    assert {item.status for item in history} >= {OperationalTaskStatus.OPEN.value, OperationalTaskStatus.IN_PROGRESS.value, OperationalTaskStatus.COMPLETED.value}
    assert len(audits) >= 3
    assert len(outbox) >= 3
    assert all(item.correlation_id for item in audits)


@pytest.mark.asyncio
async def test_dependencies_reject_cycles_block_downstream_and_cascade_unblock(db_session: AsyncSession):
    actor, owner, study, site, _query = await _context(db_session)
    service = WorkManagementService()
    first = await _task(service, db_session, actor, owner, study, site, "First")
    second = await _task(service, db_session, actor, owner, study, site, "Second")
    third = await _task(service, db_session, actor, owner, study, site, "Third")

    await service.add_dependency(db_session, first, second, actor.id, reason="Second first")
    await service.add_dependency(db_session, second, third, actor.id, reason="Third first")
    assert first.status == OperationalTaskStatus.BLOCKED.value
    assert second.status == OperationalTaskStatus.BLOCKED.value

    with pytest.raises(ConflictError, match="cycle"):
        await service.add_dependency(db_session, third, first, actor.id, reason="invalid cycle")

    await service.transition_task_status(db_session, third, OperationalTaskStatus.COMPLETED, actor.id, reason="Third done")
    assert second.status == OperationalTaskStatus.OPEN.value
    await service.transition_task_status(db_session, second, OperationalTaskStatus.COMPLETED, actor.id, reason="Second done")
    assert first.status == OperationalTaskStatus.OPEN.value
    assert len((await db_session.execute(select(TaskDependency))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_contacts_and_escalations_are_scoped_and_environment_gated(db_session: AsyncSession):
    actor, owner, study, site, _query = await _context(db_session)
    service = WorkManagementService()
    contact = await service.create_contact(
        db_session,
        actor_id=actor.id,
        study_id=study.id,
        site_id=site.id,
        name="Site coordinator",
        role="Coordinator",
        organization="Operations",
        owner_id=owner.id,
    )
    assert contact.status == OperationalContactStatus.ACTIVE.value
    assert contact.owner_id == owner.id
    await service.transition_contact_status(
        db_session, contact, OperationalContactStatus.INACTIVE, actor.id, reason="No longer assigned"
    )
    assert contact.status == OperationalContactStatus.INACTIVE.value

    task = await _task(service, db_session, actor, owner, study, site, "Escalated")
    with pytest.raises(BusinessRuleError, match="disabled"):
        await service.create_escalation(
            db_session, {"task_id": task.id, "owner_id": owner.id, "reason": "Deadline risk"}, actor.id
        )

    enabled = WorkManagementService(escalations_enabled=True)
    escalation = await enabled.create_escalation(
        db_session,
        {
            "task_id": task.id,
            "owner_id": owner.id,
            "reason": "Deadline risk",
            "deadline": datetime.now(UTC) + timedelta(days=1),
        },
        actor.id,
        correlation_id="escalation-correlation",
    )
    await enabled.transition_escalation_status(
        db_session, escalation, EscalationStatus.RESOLVED, actor.id, reason="Owner acknowledged"
    )
    assert escalation.status == EscalationStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_transaction_rollback_removes_task_audit_and_outbox_together(db_session: AsyncSession):
    actor, owner, study, site, _query = await _context(db_session)
    service = WorkManagementService()
    await _task(service, db_session, actor, owner, study, site, "Rolled back")
    await db_session.rollback()

    assert not (await db_session.execute(select(OperationalTask))).scalars().all()
    assert not (await db_session.execute(select(AuditEvent))).scalars().all()
    assert not (await db_session.execute(select(CTMSStatusHistory))).scalars().all()
    assert not (await db_session.execute(select(CTMSOutbox))).scalars().all()
