"""Focused API tests for clinical review routes (Requirements 15.1-15.3, 21.1)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.identity import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.models.review import ReviewStatus
from app.models.site import Site, SiteStatus, StudySiteUser
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitDefinition, VisitInstance


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from app.models.form_data import FieldValue
    from app.models.form_metadata import (
        Codelist,
        CodelistItem,
        FieldDefinition,
        FormSection,
    )
    from app.models.notification import Notification

    tables = [
        model.__table__
        for model in (
            Permission,
            Role,
            RolePermission,
            User,
            UserRole,
            Study,
            StudyVersion,
            Site,
            StudySiteUser,
            Subject,
            VisitDefinition,
            VisitInstance,
            FormDefinition,
            FormSection,
            FieldDefinition,
            Codelist,
            CodelistItem,
            FormInstance,
            FieldValue,
            ReviewStatus,
            AuditEvent,
            Notification,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession):
    permission = Permission(
        id=uuid.uuid4(), code="review.manage", description="Manage clinical review"
    )
    role = Role(
        id=uuid.uuid4(), name="Medical Reviewer", scope_level="system", is_system=True
    )
    user = User(
        id=uuid.uuid4(),
        email="reviewer@example.com",
        password_hash=hash_password("pw"),
        first_name="Medical",
        last_name="Reviewer",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([permission, role, user])
    await db_session.flush()
    db_session.add_all([
        RolePermission(role_id=role.id, permission_id=permission.id),
        UserRole(user_id=user.id, role_id=role.id),
    ])

    study = Study(
        id=uuid.uuid4(),
        study_code="REVIEW-001",
        title="Review Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=user.id,
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Review Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    subject = Subject(
        id=uuid.uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="101-0001",
        status=SubjectStatus.enrolled,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Review Form",
        form_code="REV",
        display_order=1,
        is_repeating=False,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([study, version, site, subject, form_definition])
    await db_session.flush()

    first = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        status=FormInstanceStatus.submitted,
        created_at=datetime.now(UTC),
    )
    second = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        status=FormInstanceStatus.submitted,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([first, second])
    await db_session.flush()
    return {"user": user, "study": study, "subject": subject, "first": first, "second": second}


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(
            bind=async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


class TestReviewRoutes:
    async def test_mark_reviewed_returns_status_and_audits(
        self, client, db_session, seeded
    ):
        response = await client.post(
            f"/api/v1/form-instances/{seeded['first'].id}/review",
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["form_instance_id"] == str(seeded["first"].id)
        assert payload["is_reviewed"] is True
        assert payload["reviewed_by"] == str(seeded["user"].id)
        assert payload["reviewed_at"] is not None

        status = (
            await db_session.execute(
                select(ReviewStatus).where(
                    ReviewStatus.form_instance_id == seeded["first"].id
                )
            )
        ).scalar_one()
        event = (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "review_status",
                    AuditEvent.entity_id == status.id,
                    AuditEvent.action == "mark_reviewed",
                )
            )
        ).scalar_one()
        assert status.is_reviewed is True
        assert event.actor_id == seeded["user"].id
        assert response.headers["x-request-id"]

    async def test_unreview_returns_not_reviewed_status(self, client, seeded):
        reviewed = await client.post(
            f"/api/v1/form-instances/{seeded['first'].id}/review",
            headers=auth(seeded["user"]),
        )
        assert reviewed.status_code == 200

        response = await client.post(
            f"/api/v1/form-instances/{seeded['first'].id}/unreview",
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["is_reviewed"] is False
        assert payload["reviewed_by"] is None
        assert payload["reviewed_at"] is None

    async def test_review_progress_uses_study_scope(self, client, seeded):
        reviewed = await client.post(
            f"/api/v1/form-instances/{seeded['first'].id}/review",
            headers=auth(seeded["user"]),
        )
        assert reviewed.status_code == 200

        response = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/review-progress",
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 200
        assert response.json() == {"reviewed": 1, "not_reviewed": 1}

    async def test_review_routes_require_permission(self, client, db_session, seeded):
        nobody = User(
            id=uuid.uuid4(),
            email="nobody@example.com",
            password_hash=hash_password("pw"),
            first_name="No",
            last_name="Access",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(nobody)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/form-instances/{seeded['first'].id}/review",
            headers=auth(nobody),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"

    async def test_review_mutation_rejects_out_of_scope_study(
        self, client, db_session, seeded
    ):
        role = Role(
            id=uuid.uuid4(),
            name="Scoped Reviewer",
            scope_level="study",
            is_system=False,
        )
        permission = (
            await db_session.execute(
                select(Permission).where(Permission.code == "review.manage")
            )
        ).scalar_one()
        out_of_scope = User(
            id=uuid.uuid4(),
            email="other-study@example.com",
            password_hash=hash_password("pw"),
            first_name="Other",
            last_name="Study",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add_all([role, out_of_scope])
        await db_session.flush()
        db_session.add_all([
            RolePermission(role_id=role.id, permission_id=permission.id),
            UserRole(
                user_id=out_of_scope.id,
                role_id=role.id,
                study_id=uuid.uuid4(),
            ),
        ])
        await db_session.flush()

        response = await client.post(
            f"/api/v1/form-instances/{seeded['first'].id}/review",
            headers=auth(out_of_scope),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"

    async def test_review_route_requires_authentication(self, client, seeded):
        response = await client.get(
            f"/api/v1/studies/{seeded['study'].id}/review-progress"
        )
        assert response.status_code == 401
        assert "error" in response.json()
