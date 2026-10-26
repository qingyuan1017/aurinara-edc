"""Focused route tests for task 19.5 edit-check endpoints."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.edc.edit_check import EditCheck, ValidationResult
from app.models.edc.form_data import FormInstance
from app.models.edc.form_metadata import FormDefinition
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import Permission, Role, RolePermission, User, UserRole, UserStatus


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession):
    # Designer edit-check routes now use the module-scoped Designer_Module
    # codes (Requirement 10). Seed both so the Designer_Role can author and
    # test rules.
    permission = Permission(
        id=uuid.uuid4(),
        code="designer.editcheck.configure",
        description="Configure edit checks",
    )
    test_permission = Permission(
        id=uuid.uuid4(),
        code="designer.editcheck.test",
        description="Test edit checks",
    )
    role = Role(id=uuid.uuid4(), name="Designer_Role", scope_level="system", is_system=True)
    user = User(
        id=uuid.uuid4(),
        email="edit-checks@example.test",
        password_hash=hash_password("pw"),
        first_name="Edit",
        last_name="Checks",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([permission, test_permission, role, user])
    await db_session.flush()
    db_session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=permission.id),
            RolePermission(role_id=role.id, permission_id=test_permission.id),
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )

    study = Study(
        id=uuid.uuid4(),
        study_code="EC-001",
        title="Edit Check Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Test Site",
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
        name="Demographics",
        form_code="DM",
        display_order=1,
        is_repeating=False,
        created_at=datetime.now(UTC),
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        # design_version_id is now not-null (bound published design, R2.7/R7.3);
        # bind the operational record to the seeded version.
        design_version_id=version.id,
        data_jsonb={"age": 21},
        created_at=datetime.now(UTC),
    )
    db_session.add_all([study, version, site, subject, form_definition, form_instance])
    await db_session.flush()
    return {
        "user": user,
        "study": study,
        "version": version,
        "form_instance": form_instance,
    }


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
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


RULE = {"field": "age", "operator": ">", "value": 18}


class TestEditCheckRoutes:
    async def test_crud_and_study_version_lookup(self, client, seeded, db_session):
        headers = auth(seeded["user"])
        created = await client.post(
            f"/api/v1/designer/studies/{seeded['study'].id}/edit-checks",
            params={"study_version_id": str(seeded["version"].id)},
            json={"name": "Adult age", "rule_json": RULE, "severity": "warning"},
            headers=headers,
        )
        assert created.status_code == 201
        check_id = created.json()["id"]
        assert created.json()["study_version_id"] == str(seeded["version"].id)

        listed = await client.get(
            f"/api/v1/designer/studies/{seeded['study'].id}/edit-checks", headers=headers
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [check_id]

        fetched = await client.get(f"/api/v1/designer/edit-checks/{check_id}", headers=headers)
        assert fetched.status_code == 200

        patched = await client.patch(
            f"/api/v1/designer/edit-checks/{check_id}",
            json={"description": "Updated description"},
            headers=headers,
        )
        assert patched.status_code == 200
        assert patched.json()["description"] == "Updated description"
        event = (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "edit_check",
                    AuditEvent.entity_id == uuid.UUID(check_id),
                    AuditEvent.action == "update",
                )
            )
        ).scalar_one()
        assert event.actor_id == seeded["user"].id

        deleted = await client.delete(f"/api/v1/designer/edit-checks/{check_id}", headers=headers)
        assert deleted.status_code == 204
        assert (
            await db_session.get(EditCheck, uuid.UUID(check_id), populate_existing=True)
        ) is None
        delete_event = (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "edit_check",
                    AuditEvent.entity_id == uuid.UUID(check_id),
                    AuditEvent.action == "delete",
                )
            )
        ).scalar_one()
        assert delete_event.actor_id == seeded["user"].id

    async def test_delete_rejects_check_with_validation_results(self, client, seeded, db_session):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Executed check",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        result = ValidationResult(
            id=uuid.uuid4(),
            edit_check_id=check.id,
            form_instance_id=seeded["form_instance"].id,
            severity="warning",
            outcome="failed",
            message="Persisted validation result",
            is_resolved=False,
            created_at=datetime.now(UTC),
        )
        db_session.add_all([check, result])
        await db_session.flush()

        response = await client.delete(
            f"/api/v1/designer/edit-checks/{check.id}",
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ConflictError"
        assert await db_session.get(EditCheck, check.id) is not None

    async def test_delete_rejects_check_from_published_version(self, client, seeded, db_session):
        seeded["version"].status = StudyVersionStatus.published
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Published check",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()

        response = await client.delete(
            f"/api/v1/designer/edit-checks/{check.id}",
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BusinessRuleError"
        assert await db_session.get(EditCheck, check.id) is not None

    async def test_test_endpoint_evaluates_without_persistence(self, client, seeded, db_session):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Adult age",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/designer/edit-checks/{check.id}/test",
            json={"sample_data": {"age": 21}},
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        assert response.json()["outcome"] is True
        assert response.json()["persisted"] is False
        assert (await db_session.execute(select(ValidationResult))).scalars().all() == []

    async def test_retest_endpoint_clears_hold_and_records_hashed_evidence(
        self, client, seeded, db_session
    ):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Imported adult age",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            needs_retesting=True,
            retesting_reason="Imported rule requires review",
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/designer/edit-checks/{check.id}/retest",
            json={
                "sample_data": {"age": 21},
                "expected_matched": True,
                "review_note": "Verified the imported comparison and warning behavior.",
            },
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 200
        assert response.json()["matched"] is True
        assert response.json()["needs_retesting"] is False
        await db_session.refresh(check)
        assert check.needs_retesting is False
        assert check.retesting_reason is None
        event = (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "edit_check",
                    AuditEvent.entity_id == check.id,
                    AuditEvent.action == "retest",
                )
            )
        ).scalar_one()
        assert "sample_data_sha256" in (event.new_value or "")
        assert '"age": 21' not in (event.new_value or "")

    async def test_retest_endpoint_preserves_hold_when_outcome_differs(
        self, client, seeded, db_session
    ):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Imported adult age",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            needs_retesting=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()
        await db_session.commit()

        response = await client.post(
            f"/api/v1/designer/edit-checks/{check.id}/retest",
            json={
                "sample_data": {"age": 21},
                "expected_matched": False,
                "review_note": "Expected this sample not to match.",
            },
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ConflictError"
        await db_session.refresh(check)
        assert check.needs_retesting is True

    async def test_bulk_retest_clears_all_pending_holds_with_per_rule_audit(
        self, client, seeded, db_session
    ):
        pending = [
            EditCheck(
                id=uuid.uuid4(),
                study_version_id=seeded["version"].id,
                name=f"Imported check {index}",
                rule_json={"field": "age", "operator": ">", "value": index},
                severity="warning",
                is_active=True,
                needs_retesting=True,
                retesting_reason="Imported rule requires review",
                created_at=datetime.now(UTC),
            )
            for index in (18, 21)
        ]
        already_reviewed = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Previously reviewed check",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            needs_retesting=False,
            created_at=datetime.now(UTC),
        )
        db_session.add_all([*pending, already_reviewed])
        await db_session.flush()

        response = await client.post(
            f"/api/v1/designer/studies/{seeded['study'].id}/edit-checks/retest-all",
            params={"study_version_id": str(seeded["version"].id)},
            json={
                "review_note": "Reviewed imported rules against the approved specification.",
                "acknowledge_without_individual_samples": True,
            },
            headers=auth(seeded["user"]),
        )

        assert response.status_code == 200
        assert response.json()["reviewed_count"] == 2
        assert response.json()["remaining_count"] == 0
        for check in pending:
            await db_session.refresh(check)
            assert check.needs_retesting is False
            assert check.retesting_reason is None
        events = (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "retest_bulk")
            )
        ).scalars().all()
        assert {event.entity_id for event in events} == {check.id for check in pending}
        assert all("rule_json_sha256" in (event.new_value or "") for event in events)

    async def test_run_evaluates_forms_and_persists_failures(self, client, seeded, db_session):
        check = EditCheck(
            id=uuid.uuid4(),
            study_version_id=seeded["version"].id,
            name="Adult age",
            rule_json=RULE,
            severity="warning",
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(check)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/designer/studies/{seeded['study'].id}/edit-checks/run",
            json={"study_version_id": str(seeded["version"].id)},
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 200
        assert response.json()["evaluated_form_instances"] == 1
        assert response.json()["failed_checks"] == 1
        assert len(response.json()["results"]) == 1
        persisted = (await db_session.execute(select(ValidationResult))).scalars().all()
        assert len(persisted) == 1

    async def test_routes_enforce_server_side_authorization(self, client, db_session, seeded):
        unauthorized = User(
            id=uuid.uuid4(),
            email="unauthorized@example.test",
            password_hash=hash_password("pw"),
            first_name="No",
            last_name="Access",
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        db_session.add(unauthorized)
        await db_session.flush()

        response = await client.get(
            f"/api/v1/designer/studies/{seeded['study'].id}/edit-checks",
            headers=auth(unauthorized),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AuthorizationError"

    async def test_invalid_dsl_uses_standard_error_envelope(self, client, seeded):
        response = await client.post(
            f"/api/v1/designer/studies/{seeded['study'].id}/edit-checks",
            json={
                "name": "Unsafe rule",
                "rule_json": {"field": "age", "operator": "exec", "value": "x"},
                "severity": "warning",
            },
            headers=auth(seeded["user"]),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ValidationError"
        assert response.json()["error"]["details"]["path"] == "$.operator"
