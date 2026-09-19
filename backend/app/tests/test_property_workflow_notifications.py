"""Property-based coverage for workflow notification recipients and state.

# Feature: clinical-edc-system, Property 36: Workflow events create notifications for the right recipients
**Validates: Requirements 28.1, 28.2, 28.3**

Each generated scenario exercises query assignment, form submission, and export
completion against the real NotificationService and a transactional SQLite ORM
schema. Active users are notified only when their assigned role covers the
workflow scope; inactive and out-of-scope users are excluded. Created events
remain unread and owned by exactly the addressed user.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.export import Export, ExportStatus, ExportType
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.identity import Role, ScopeLevel, User, UserRole, UserStatus
from app.models.notification import Notification, NotificationStatus
from app.models.query import Query, QueryTargetType, QueryType
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.services.notification_service import NotificationService

ROLE_SCOPE = st.sampled_from([
    ScopeLevel.system,
    ScopeLevel.study,
    ScopeLevel.site,
])
CANDIDATE_EVENT = st.sampled_from(["query", "review"])
CANDIDATE_STATUS = st.sampled_from([UserStatus.active, UserStatus.inactive])


@st.composite
def notification_scenario(draw: st.DrawFn) -> dict:
    """Generate role scopes and additional assigned users for both events."""
    return {
        "query_scope": draw(ROLE_SCOPE),
        "reviewer_scope": draw(ROLE_SCOPE),
        "extras": draw(
            st.lists(
                st.tuples(CANDIDATE_EVENT, CANDIDATE_STATUS, st.booleans()),
                min_size=0,
                max_size=8,
            )
        ),
    }


@pytest.fixture
async def db_session():
    """Provide an isolated SQLite database for each generated scenario."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _scope_assignment(
    role_scope: ScopeLevel,
    in_scope: bool,
    *,
    study_id: uuid.UUID,
    site_id: uuid.UUID,
    other_study_id: uuid.UUID,
    other_site_id: uuid.UUID,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return assignment columns that either cover or miss the event scope."""
    if in_scope:
        if role_scope == ScopeLevel.system:
            return None, None
        if role_scope == ScopeLevel.study:
            return study_id, None
        return study_id, site_id

    if role_scope == ScopeLevel.system:
        # Non-null columns intentionally do not satisfy a system-scope grant.
        return other_study_id, other_site_id
    if role_scope == ScopeLevel.study:
        return other_study_id, None
    return study_id, other_site_id


def _make_user(label: str, status: UserStatus) -> User:
    user_id = uuid.uuid4()
    return User(
        id=user_id,
        email=f"{label}-{user_id}@example.test",
        first_name="Property",
        last_name=label,
        status=status,
        mfa_enabled=False,
        created_at=datetime.now(UTC),
    )


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(scenario=notification_scenario())
@pytest.mark.asyncio
async def test_workflow_notifications_target_active_in_scope_users(
    db_session: AsyncSession,
    scenario: dict,
):
    """All workflow notifications target exactly the eligible owners."""
    now = datetime.now(UTC)
    study_id = uuid.uuid4()
    other_study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    other_site_id = uuid.uuid4()
    other_study_site_id = uuid.uuid4()
    actor = _make_user("actor", UserStatus.active)
    requester = _make_user("requester", UserStatus.active)

    study = Study(
        id=study_id,
        study_code=f"PROP-{study_id}",
        title="Notification property study",
        status=StudyStatus.active,
        created_by=actor.id,
        created_at=now,
    )
    other_study = Study(
        id=other_study_id,
        study_code=f"OTHER-{other_study_id}",
        title="Out of scope study",
        status=StudyStatus.active,
        created_by=actor.id,
        created_at=now,
    )
    site = Site(
        id=site_id,
        study_id=study_id,
        site_number="1001",
        name="Notification site",
        status=SiteStatus.active,
        created_at=now,
    )
    other_site = Site(
        id=other_site_id,
        study_id=study_id,
        site_number="1002",
        name="Other site",
        status=SiteStatus.active,
        created_at=now,
    )
    other_study_site = Site(
        id=other_study_site_id,
        study_id=other_study_id,
        site_number="2001",
        name="Other study site",
        status=SiteStatus.active,
        created_at=now,
    )
    query_role = Role(
        id=uuid.uuid4(),
        name="Query Assignee",
        scope_level=scenario["query_scope"],
        created_at=now,
    )
    reviewer_role = Role(
        id=uuid.uuid4(),
        name="Medical Reviewer",
        scope_level=scenario["reviewer_scope"],
        created_at=now,
    )

    users = [actor, requester]
    assignments: list[UserRole] = []
    expected_by_user: defaultdict[uuid.UUID, list[str]] = defaultdict(list)
    # Always include active eligible, inactive eligible, and active ineligible
    # users for each workflow role; generated extras add arbitrary combinations.
    candidate_specs = [
        ("query", UserStatus.active, True),
        ("query", UserStatus.inactive, True),
        ("query", UserStatus.active, False),
        ("review", UserStatus.active, True),
        ("review", UserStatus.inactive, True),
        ("review", UserStatus.active, False),
        *scenario["extras"],
    ]

    for index, (event_kind, status, in_scope) in enumerate(candidate_specs):
        role = query_role if event_kind == "query" else reviewer_role
        role_scope = role.scope_level
        user = _make_user(f"candidate-{index}", status)
        assigned_study_id, assigned_site_id = _scope_assignment(
            role_scope,
            in_scope,
            study_id=study_id,
            site_id=site_id,
            other_study_id=other_study_id,
            other_site_id=other_site_id,
        )
        assignment = UserRole(
            id=uuid.uuid4(),
            user_id=user.id,
            role_id=role.id,
            study_id=assigned_study_id,
            site_id=assigned_site_id,
            assigned_at=now,
        )
        users.append(user)
        assignments.append(assignment)
        if status == UserStatus.active and in_scope:
            expected_by_user[user.id].append(
                "query_assigned" if event_kind == "query" else "form_submitted"
            )

    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study_id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=now,
        published_by=actor.id,
        created_at=now,
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Notification Form",
        form_code="NOTIF",
        display_order=1,
        is_repeating=False,
        created_at=now,
    )
    subject = Subject(
        id=uuid.uuid4(),
        study_id=study_id,
        site_id=site_id,
        study_version_id=version.id,
        subject_number="1001-0001",
        status=SubjectStatus.enrolled,
        created_by=actor.id,
        created_at=now,
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        status=FormInstanceStatus.submitted,
        submitted_by=actor.id,
        created_at=now,
        subject=subject,
    )
    query = Query(
        id=uuid.uuid4(),
        study_id=study_id,
        site_id=site_id,
        subject_id=subject.id,
        target_type=QueryTargetType.form_instance,
        target_id=form_instance.id,
        text="Please clarify this value",
        query_type=QueryType.manual,
        assigned_role=query_role.name,
        created_by=actor.id,
    )
    export = Export(
        id=uuid.uuid4(),
        study_id=study_id,
        export_type=ExportType.csv,
        status=ExportStatus.completed,
        requested_by=requester.id,
        file_path="exports/notification-property.csv",
        file_size=42,
        created_at=now,
    )
    existing_read = Notification(
        id=uuid.uuid4(),
        user_id=requester.id,
        type="existing_read",
        payload_json={},
        status=NotificationStatus.read,
        created_at=now,
    )
    existing_archived = Notification(
        id=uuid.uuid4(),
        user_id=requester.id,
        type="existing_archived",
        payload_json={},
        status=NotificationStatus.archived,
        created_at=now,
    )

    db_session.add_all(
        [
            actor,
            requester,
            *users[2:],
            study,
            other_study,
            site,
            other_site,
            other_study_site,
            query_role,
            reviewer_role,
            *assignments,
            version,
            form_definition,
            subject,
            form_instance,
            query,
            export,
            existing_read,
            existing_archived,
        ]
    )
    await db_session.flush()

    service = NotificationService()
    query_notifications = await service.on_query_assigned(db_session, query)
    form_notifications = await service.on_form_submitted(db_session, form_instance)
    export_notifications = await service.on_export_completed(db_session, export)

    assert {item.user_id for item in query_notifications} == {
        user_id
        for user_id, event_types in expected_by_user.items()
        if "query_assigned" in event_types
    }
    assert {item.user_id for item in form_notifications} == {
        user_id
        for user_id, event_types in expected_by_user.items()
        if "form_submitted" in event_types
    }
    assert [item.user_id for item in export_notifications] == [requester.id]

    workflow_notifications = [
        *query_notifications,
        *form_notifications,
        *export_notifications,
    ]
    assert all(item.status == NotificationStatus.unread for item in workflow_notifications)
    assert all(item.user_id != actor.id for item in workflow_notifications)
    assert all(item.user_id != requester.id for item in [*query_notifications, *form_notifications])

    # Every addressed user owns only their own unread workflow events; the
    # pre-existing Read/Archived records remain excluded from the unread view.
    expected_by_user[requester.id].append("export_completed")
    for user in users:
        unread = await service.list_unread(db_session, user.id)
        actual_types = Counter(item.type for item in unread)
        assert actual_types == Counter(expected_by_user[user.id])
        assert all(item.user_id == user.id for item in unread)
        assert all(item.status == NotificationStatus.unread for item in unread)

    all_notifications = (
        await db_session.execute(select(Notification))
    ).scalars().all()
    assert existing_read.status == NotificationStatus.read
    assert existing_archived.status == NotificationStatus.archived
    assert len(all_notifications) == len(workflow_notifications) + 2
    await db_session.rollback()
