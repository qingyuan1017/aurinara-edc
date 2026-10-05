"""Example-based coverage for PV safety notification triggers (Task 6.3).

Feature: pv-safety-module, Task 6.3
Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8

Exercises the ``PVNotificationService`` against an in-memory database so the
three PV safety triggers (serious-case creation, Regulatory_Clock warning
window, and export outcome), the Unread/Read/Archived transition state machine,
Unread listing, warning dedupe, and the no-recipient Audit_Event are covered
end to end. The ``Notification_Service`` remains shared; only PV triggers and
recipient resolution are PV-owned.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import BusinessRuleError
from app.core.pv import ActorContext, Module
from app.models.audit import AuditEvent
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
    UserStatus,
)
from app.models.notification import Notification, NotificationStatus
from app.services.pv_notification_service import (
    DEFAULT_SERIOUS_CASE_PERMISSION,
    NOTIFICATION_TYPE_CLOCK_WARNING,
    NOTIFICATION_TYPE_EXPORT_OUTCOME,
    NOTIFICATION_TYPE_SERIOUS_CASE,
    PVNotificationService,
)


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _actor(user_id) -> ActorContext:
    return ActorContext(user_id=user_id, request_id=str(uuid4()), correlation_id=str(uuid4()))


async def _make_user(session: AsyncSession, *, status: UserStatus = UserStatus.active) -> User:
    user = User(
        email=f"pv-{uuid4()}@example.test",
        first_name="PV",
        last_name="User",
        status=status,
    )
    session.add(user)
    await session.flush()
    return user


async def _grant_pv_role(
    session: AsyncSession,
    *,
    user: User,
    scope_level: ScopeLevel,
    study_id=None,
    site_id=None,
    permission_code: str = DEFAULT_SERIOUS_CASE_PERMISSION,
) -> None:
    """Assign a PV role granting ``permission_code`` at the given scope."""
    permission = (
        await session.execute(select(Permission).where(Permission.code == permission_code))
    ).scalars().first()
    if permission is None:
        permission = Permission(code=permission_code, description="PV safety permission")
        session.add(permission)
        await session.flush()

    role = Role(name=f"PVRole-{uuid4()}", scope_level=scope_level, is_system=False)
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.add(
        UserRole(user_id=user.id, role_id=role.id, study_id=study_id, site_id=site_id)
    )
    await session.flush()


async def _count_notifications(session: AsyncSession, *, notification_type: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.type == notification_type)
            )
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# 14.1 serious-case creation notifies each resolved recipient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serious_case_notifies_each_resolved_recipient(db_session: AsyncSession):
    study_id = uuid4()
    site_id = uuid4()
    actor_user = await _make_user(db_session)

    study_recipient = await _make_user(db_session)
    await _grant_pv_role(
        db_session, user=study_recipient, scope_level=ScopeLevel.study, study_id=study_id
    )
    site_recipient = await _make_user(db_session)
    await _grant_pv_role(
        db_session,
        user=site_recipient,
        scope_level=ScopeLevel.site,
        study_id=study_id,
        site_id=site_id,
    )
    system_recipient = await _make_user(db_session)
    await _grant_pv_role(db_session, user=system_recipient, scope_level=ScopeLevel.system)

    service = PVNotificationService()
    notifications = await service.on_serious_case_created(
        db_session,
        case_id=uuid4(),
        study_id=study_id,
        site_id=site_id,
        actor=_actor(actor_user.id),
    )

    recipient_ids = {n.user_id for n in notifications}
    assert recipient_ids == {study_recipient.id, site_recipient.id, system_recipient.id}
    assert all(n.module == Module.PV.value for n in notifications)
    assert all(n.type == NOTIFICATION_TYPE_SERIOUS_CASE for n in notifications)
    assert all(n.status == NotificationStatus.unread for n in notifications)


@pytest.mark.asyncio
async def test_serious_case_excludes_out_of_scope_and_inactive_users(db_session: AsyncSession):
    study_id = uuid4()
    site_id = uuid4()
    actor_user = await _make_user(db_session)

    # Recipient scoped to a different study is not resolved.
    other_study_user = await _make_user(db_session)
    await _grant_pv_role(
        db_session, user=other_study_user, scope_level=ScopeLevel.study, study_id=uuid4()
    )
    # Inactive user in scope is not resolved.
    inactive_user = await _make_user(db_session, status=UserStatus.inactive)
    await _grant_pv_role(
        db_session, user=inactive_user, scope_level=ScopeLevel.study, study_id=study_id
    )
    in_scope_user = await _make_user(db_session)
    await _grant_pv_role(
        db_session, user=in_scope_user, scope_level=ScopeLevel.study, study_id=study_id
    )

    service = PVNotificationService()
    notifications = await service.on_serious_case_created(
        db_session,
        case_id=uuid4(),
        study_id=study_id,
        site_id=site_id,
        actor=_actor(actor_user.id),
    )

    assert {n.user_id for n in notifications} == {in_scope_user.id}


# ---------------------------------------------------------------------------
# 14.8 no recipient resolved: no notification, one PV Audit_Event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serious_case_no_recipient_records_single_audit_event(db_session: AsyncSession):
    study_id = uuid4()
    site_id = uuid4()
    case_id = uuid4()
    actor_user = await _make_user(db_session)

    service = PVNotificationService()
    notifications = await service.on_serious_case_created(
        db_session,
        case_id=case_id,
        study_id=study_id,
        site_id=site_id,
        actor=_actor(actor_user.id),
    )

    assert notifications == []
    assert await _count_notifications(
        db_session, notification_type=NOTIFICATION_TYPE_SERIOUS_CASE
    ) == 0

    audits = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "safety_notification",
                    AuditEvent.action == "no_recipient_resolved",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].module == "PV"
    assert audits[0].entity_id == case_id


# ---------------------------------------------------------------------------
# 14.2 Regulatory_Clock warning window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clock_warning_within_window_creates_notification(db_session: AsyncSession):
    recipient = await _make_user(db_session)
    today = date(2025, 1, 1)
    service = PVNotificationService()

    notifications = await service.on_regulatory_clock_warning(
        db_session,
        report_id=uuid4(),
        report_status="Pending",
        due_date=today + timedelta(days=10),
        recipient_ids=[recipient.id],
        today_utc=today,
    )

    assert len(notifications) == 1
    note = notifications[0]
    assert note.type == NOTIFICATION_TYPE_CLOCK_WARNING
    assert note.module == Module.PV.value
    assert note.payload_json["due_date"] == (today + timedelta(days=10)).isoformat()
    assert "report_id" in note.payload_json


@pytest.mark.asyncio
@pytest.mark.parametrize("offset_days", [1, 30])
async def test_clock_warning_window_boundaries_included(db_session: AsyncSession, offset_days: int):
    recipient = await _make_user(db_session)
    today = date(2025, 6, 1)
    service = PVNotificationService()

    notifications = await service.on_regulatory_clock_warning(
        db_session,
        report_id=uuid4(),
        report_status="Pending",
        due_date=today + timedelta(days=offset_days),
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_clock_warning_outside_window_creates_none(db_session: AsyncSession):
    recipient = await _make_user(db_session)
    today = date(2025, 6, 1)
    service = PVNotificationService()

    # Due date beyond the 30-day window.
    beyond = await service.on_regulatory_clock_warning(
        db_session,
        report_id=uuid4(),
        report_status="Pending",
        due_date=today + timedelta(days=31),
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert beyond == []

    # Past-due date is not a warning-window event.
    past_due = await service.on_regulatory_clock_warning(
        db_session,
        report_id=uuid4(),
        report_status="Pending",
        due_date=today - timedelta(days=1),
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert past_due == []


@pytest.mark.asyncio
async def test_clock_warning_suppressed_when_report_submitted(db_session: AsyncSession):
    recipient = await _make_user(db_session)
    today = date(2025, 6, 1)
    service = PVNotificationService()

    notifications = await service.on_regulatory_clock_warning(
        db_session,
        report_id=uuid4(),
        report_status="Submitted",
        due_date=today + timedelta(days=5),
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert notifications == []


# ---------------------------------------------------------------------------
# 14.7 dedupe warning notifications for same report + due date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clock_warning_deduped_for_same_report_and_due_date(db_session: AsyncSession):
    recipient = await _make_user(db_session)
    today = date(2025, 6, 1)
    report_id = uuid4()
    due_date = today + timedelta(days=7)
    service = PVNotificationService()

    first = await service.on_regulatory_clock_warning(
        db_session,
        report_id=report_id,
        report_status="Pending",
        due_date=due_date,
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert len(first) == 1

    # Re-evaluation with an unarchived notification present creates none.
    second = await service.on_regulatory_clock_warning(
        db_session,
        report_id=report_id,
        report_status="Pending",
        due_date=due_date,
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert second == []
    assert await _count_notifications(
        db_session, notification_type=NOTIFICATION_TYPE_CLOCK_WARNING
    ) == 1


@pytest.mark.asyncio
async def test_clock_warning_new_due_date_not_deduped(db_session: AsyncSession):
    recipient = await _make_user(db_session)
    today = date(2025, 6, 1)
    report_id = uuid4()
    service = PVNotificationService()

    await service.on_regulatory_clock_warning(
        db_session,
        report_id=report_id,
        report_status="Pending",
        due_date=today + timedelta(days=7),
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    # A different due date for the same report is a distinct warning.
    second = await service.on_regulatory_clock_warning(
        db_session,
        report_id=report_id,
        report_status="Pending",
        due_date=today + timedelta(days=3),
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert len(second) == 1
    assert await _count_notifications(
        db_session, notification_type=NOTIFICATION_TYPE_CLOCK_WARNING
    ) == 2


@pytest.mark.asyncio
async def test_clock_warning_archived_does_not_suppress(db_session: AsyncSession):
    recipient = await _make_user(db_session)
    today = date(2025, 6, 1)
    report_id = uuid4()
    due_date = today + timedelta(days=7)
    service = PVNotificationService()

    first = await service.on_regulatory_clock_warning(
        db_session,
        report_id=report_id,
        report_status="Pending",
        due_date=due_date,
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    # Archive the existing notification; it no longer suppresses a new warning.
    await service.archive(db_session, notification=first[0], user_id=recipient.id)

    second = await service.on_regulatory_clock_warning(
        db_session,
        report_id=report_id,
        report_status="Pending",
        due_date=due_date,
        recipient_ids=[recipient.id],
        today_utc=today,
    )
    assert len(second) == 1


# ---------------------------------------------------------------------------
# 14.3 export outcome notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["Completed", "Failed"])
async def test_export_outcome_notifies_requesting_user(db_session: AsyncSession, outcome: str):
    requester = await _make_user(db_session)
    export_job_id = uuid4()
    service = PVNotificationService()

    notifications = await service.on_export_outcome(
        db_session,
        export_job_id=export_job_id,
        outcome=outcome,
        requesting_user_id=requester.id,
    )

    assert len(notifications) == 1
    note = notifications[0]
    assert note.user_id == requester.id
    assert note.type == NOTIFICATION_TYPE_EXPORT_OUTCOME
    assert note.payload_json["outcome"] == outcome
    assert note.payload_json["export_job_id"] == str(export_job_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["Queued", "Running"])
async def test_export_outcome_ignores_non_terminal_states(db_session: AsyncSession, outcome: str):
    requester = await _make_user(db_session)
    service = PVNotificationService()

    notifications = await service.on_export_outcome(
        db_session,
        export_job_id=uuid4(),
        outcome=outcome,
        requesting_user_id=requester.id,
    )
    assert notifications == []


# ---------------------------------------------------------------------------
# 14.4 status transitions / 14.5 unread listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unread_listing_returns_only_requesting_user_unread(db_session: AsyncSession):
    study_id = uuid4()
    actor_user = await _make_user(db_session)
    recipient_a = await _make_user(db_session)
    await _grant_pv_role(
        db_session, user=recipient_a, scope_level=ScopeLevel.study, study_id=study_id
    )
    recipient_b = await _make_user(db_session)
    await _grant_pv_role(
        db_session, user=recipient_b, scope_level=ScopeLevel.study, study_id=study_id
    )

    service = PVNotificationService()
    await service.on_serious_case_created(
        db_session,
        case_id=uuid4(),
        study_id=study_id,
        site_id=None,
        actor=_actor(actor_user.id),
    )

    a_unread = await service.list_unread(db_session, user_id=recipient_a.id)
    assert len(a_unread) == 1
    assert a_unread[0].user_id == recipient_a.id

    # An unrelated user with no notifications gets an empty list.
    stranger = await _make_user(db_session)
    assert await service.list_unread(db_session, user_id=stranger.id) == []


@pytest.mark.asyncio
async def test_status_transitions_unread_to_read_to_archived(db_session: AsyncSession):
    requester = await _make_user(db_session)
    service = PVNotificationService()

    created = await service.on_export_outcome(
        db_session,
        export_job_id=uuid4(),
        outcome="Completed",
        requesting_user_id=requester.id,
    )
    note = created[0]
    assert note.status == NotificationStatus.unread

    read = await service.mark_read(db_session, notification=note, user_id=requester.id)
    assert read.status == NotificationStatus.read
    # Read no longer appears in the Unread list.
    assert await service.list_unread(db_session, user_id=requester.id) == []

    archived = await service.archive(db_session, notification=note, user_id=requester.id)
    assert archived.status == NotificationStatus.archived


@pytest.mark.asyncio
async def test_archived_cannot_transition(db_session: AsyncSession):
    requester = await _make_user(db_session)
    service = PVNotificationService()

    created = await service.on_export_outcome(
        db_session,
        export_job_id=uuid4(),
        outcome="Completed",
        requesting_user_id=requester.id,
    )
    note = created[0]
    await service.archive(db_session, notification=note, user_id=requester.id)

    with pytest.raises(BusinessRuleError):
        await service.mark_read(db_session, notification=note, user_id=requester.id)
