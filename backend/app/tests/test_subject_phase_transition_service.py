"""Tests for SubjectPhaseTransitionService, the subject-phase cascade, the
consumption read of transitions, SoA idempotency, and route authorization.

Feature: designer-frontend-overhaul, FEAT-001 (A.9, A.12).
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # register every ORM table on Base.metadata
from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.services.designer.design_consumption_service import design_consumption_service
from app.services.designer.schedule_of_assessment_service import (
    ScheduleEntryInput,
    schedule_of_assessment_service,
)
from app.services.designer.subject_phase_service import subject_phase_service
from app.services.designer.subject_phase_transition_service import (
    subject_phase_transition_service,
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


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Phase Study",
        status=StudyStatus.draft,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    session.add(version)
    await session.flush()
    return version


async def _make_phase(
    session: AsyncSession, version: StudyVersion, name: str, order: int
) -> SubjectPhaseDefinition:
    return await subject_phase_service.create_phase_definition(
        session,
        design_version_id=version.id,
        name=name,
        display_order=order,
    )


async def _count_delete_events(session: AsyncSession, entity_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.entity_id == entity_id,
                AuditEvent.action == "delete",
            )
        )
    ).scalar_one()


class TestCreateTransition:
    async def test_happy_path_persists_and_audits(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)
        actor = uuid.uuid4()

        edge = await subject_phase_transition_service.create_transition(
            db_session,
            design_version_id=version.id,
            from_phase_id=a.id,
            to_phase_id=b.id,
            label="advance",
            actor_id=actor,
        )

        assert edge.id is not None
        assert edge.from_phase_id == a.id
        assert edge.to_phase_id == b.id
        assert edge.label == "advance"

        events = (
            (
                await db_session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_type == "subject_phase_transition",
                        AuditEvent.entity_id == edge.id,
                        AuditEvent.action == "create",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1

    async def test_self_transition_rejected_persists_nothing(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)

        with pytest.raises(ValidationError):
            await subject_phase_transition_service.create_transition(
                db_session,
                design_version_id=version.id,
                from_phase_id=a.id,
                to_phase_id=a.id,
            )

        count = (
            await db_session.execute(select(func.count()).select_from(SubjectPhaseTransition))
        ).scalar_one()
        assert count == 0

    async def test_unknown_phase_raises_not_found(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)

        with pytest.raises(NotFoundError):
            await subject_phase_transition_service.create_transition(
                db_session,
                design_version_id=version.id,
                from_phase_id=a.id,
                to_phase_id=uuid.uuid4(),
            )

    async def test_cross_version_phases_rejected(self, db_session):
        version_a = await _make_draft_version(db_session)
        version_b = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version_a, "Screening", 1)
        b = await _make_phase(db_session, version_b, "Treatment", 1)

        with pytest.raises(ValidationError):
            await subject_phase_transition_service.create_transition(
                db_session,
                design_version_id=version_a.id,
                from_phase_id=a.id,
                to_phase_id=b.id,
            )

    async def test_duplicate_edge_rejected(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)

        await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=b.id
        )
        with pytest.raises(ConflictError):
            await subject_phase_transition_service.create_transition(
                db_session,
                design_version_id=version.id,
                from_phase_id=a.id,
                to_phase_id=b.id,
            )


class TestListAndDelete:
    async def test_soft_delete_removes_from_list(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)
        edge = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=b.id
        )

        listed = await subject_phase_transition_service.list_transitions(db_session, version.id)
        assert [e.id for e in listed] == [edge.id]

        await subject_phase_transition_service.delete_transition(db_session, edge.id)

        listed_after = await subject_phase_transition_service.list_transitions(
            db_session, version.id
        )
        assert listed_after == []

    async def test_delete_missing_raises_not_found(self, db_session):
        with pytest.raises(NotFoundError):
            await subject_phase_transition_service.delete_transition(db_session, uuid.uuid4())


class TestPhaseDeleteCascade:
    async def test_cascade_soft_deletes_incident_edges_both_directions(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)
        c = await _make_phase(db_session, version, "Follow-up", 3)

        # a->b and b->a touch b; a->c does NOT touch b (sibling edge).
        incoming = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=b.id
        )
        outgoing = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=b.id, to_phase_id=a.id
        )
        sibling = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=c.id
        )

        await subject_phase_service.delete_phase_definition(db_session, b.id)

        # Both incident edges soft-deleted with one delete audit each.
        for edge in (incoming, outgoing):
            refreshed = (
                await db_session.execute(
                    select(SubjectPhaseTransition).where(SubjectPhaseTransition.id == edge.id)
                )
            ).scalar_one()
            assert refreshed.deleted_at is not None
            assert await _count_delete_events(db_session, edge.id) == 1

        # Sibling edge untouched.
        refreshed_sibling = (
            await db_session.execute(
                select(SubjectPhaseTransition).where(SubjectPhaseTransition.id == sibling.id)
            )
        ).scalar_one()
        assert refreshed_sibling.deleted_at is None

        # The phase itself is soft-deleted.
        refreshed_phase = (
            await db_session.execute(
                select(SubjectPhaseDefinition).where(SubjectPhaseDefinition.id == b.id)
            )
        ).scalar_one()
        assert refreshed_phase.deleted_at is not None

    async def test_list_guard_excludes_directly_orphaned_edge(self, db_session):
        """An edge whose phase is soft-deleted without the cascade is still
        excluded by the join guard (defense-in-depth)."""
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)
        edge = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=b.id
        )

        # Soft-delete the phase directly (bypassing the cascade) so the edge is
        # orphaned but still live.
        b.deleted_at = datetime.now(UTC)
        await db_session.flush()

        refreshed = (
            await db_session.execute(
                select(SubjectPhaseTransition).where(SubjectPhaseTransition.id == edge.id)
            )
        ).scalar_one()
        assert refreshed.deleted_at is None  # edge itself still live

        listed = await subject_phase_transition_service.list_transitions(db_session, version.id)
        assert listed == []


class TestConsumption:
    async def _publish(self, session: AsyncSession, version: StudyVersion) -> None:
        version.status = StudyVersionStatus.published
        version.published_at = datetime.now(UTC)
        version.published_by = uuid.uuid4()
        await session.flush()

    async def test_rejects_draft_version(self, db_session):
        version = await _make_draft_version(db_session)
        with pytest.raises(ValidationError):
            await design_consumption_service.list_subject_phase_transitions(db_session, version.id)

    async def test_returns_edges_for_published_version(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)
        edge = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=b.id
        )
        await self._publish(db_session, version)

        views = await design_consumption_service.list_subject_phase_transitions(
            db_session, version.id
        )
        assert [v.id for v in views] == [edge.id]

    async def test_soft_deleted_edge_absent_from_consumption(self, db_session):
        version = await _make_draft_version(db_session)
        a = await _make_phase(db_session, version, "Screening", 1)
        b = await _make_phase(db_session, version, "Treatment", 2)
        edge = await subject_phase_transition_service.create_transition(
            db_session, design_version_id=version.id, from_phase_id=a.id, to_phase_id=b.id
        )
        await subject_phase_transition_service.delete_transition(db_session, edge.id)
        await self._publish(db_session, version)

        views = await design_consumption_service.list_subject_phase_transitions(
            db_session, version.id
        )
        assert views == []


class TestSoAIdempotency:
    async def test_two_saves_leave_one_live_soa(self, db_session):
        version = await _make_draft_version(db_session)
        from app.models.designer.schedule_of_assessment import (
            ScheduleOfAssessment,
            ScheduleOfAssessmentEntry,
        )

        visits = [
            VisitDefinition(
                study_version_id=version.id,
                name=f"Visit {index}",
                visit_number=index,
                display_order=index,
                is_required=True,
            )
            for index in range(1, 4)
        ]
        db_session.add_all(visits)
        await db_session.flush()

        first = await schedule_of_assessment_service.create_schedule_of_assessment(
            db_session,
            design_version_id=version.id,
            entries=[ScheduleEntryInput(procedure_name="Vitals", visit_definition_id=visits[0].id)],
        )
        second = await schedule_of_assessment_service.create_schedule_of_assessment(
            db_session,
            design_version_id=version.id,
            entries=[
                ScheduleEntryInput(procedure_name="Labs", visit_definition_id=visits[1].id),
                ScheduleEntryInput(procedure_name="ECG", visit_definition_id=visits[2].id),
            ],
        )

        live = (
            (
                await db_session.execute(
                    select(ScheduleOfAssessment).where(
                        ScheduleOfAssessment.design_version_id == version.id,
                        ScheduleOfAssessment.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(live) == 1
        assert live[0].id == second.id
        assert live[0].id != first.id

        # First SoA + its entries are soft-deleted.
        first_reloaded = (
            await db_session.execute(
                select(ScheduleOfAssessment).where(ScheduleOfAssessment.id == first.id)
            )
        ).scalar_one()
        assert first_reloaded.deleted_at is not None
        first_entries = (
            (
                await db_session.execute(
                    select(ScheduleOfAssessmentEntry).where(
                        ScheduleOfAssessmentEntry.schedule_of_assessment_id == first.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert first_entries and all(e.deleted_at is not None for e in first_entries)

        # get() returns the second (deterministic) payload.
        fetched = await schedule_of_assessment_service.get_schedule_of_assessment(
            db_session, version.id
        )
        assert fetched.id == second.id
        assert {e.procedure_name for e in fetched.entries} == {"Labs", "ECG"}

        # Audit trail has a delete (replacement) + creates.
        assert await _count_delete_events(db_session, first.id) == 1

    async def test_invalid_second_payload_leaves_first_live(self, db_session):
        version = await _make_draft_version(db_session)
        from app.models.designer.schedule_of_assessment import ScheduleOfAssessment

        visit = VisitDefinition(
            study_version_id=version.id,
            name="Visit 1",
            visit_number=1,
            display_order=1,
            is_required=True,
        )
        db_session.add(visit)
        await db_session.flush()

        first = await schedule_of_assessment_service.create_schedule_of_assessment(
            db_session,
            design_version_id=version.id,
            entries=[ScheduleEntryInput(procedure_name="Vitals", visit_definition_id=visit.id)],
        )

        # Invalid: entry maps neither a form nor a procedure.
        with pytest.raises(ValidationError):
            await schedule_of_assessment_service.create_schedule_of_assessment(
                db_session,
                design_version_id=version.id,
                entries=[ScheduleEntryInput(visit_definition_id=visit.id)],
            )

        live = (
            (
                await db_session.execute(
                    select(ScheduleOfAssessment).where(
                        ScheduleOfAssessment.design_version_id == version.id,
                        ScheduleOfAssessment.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(live) == 1
        assert live[0].id == first.id


# ---------------------------------------------------------------------------
# Route authorization tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def route_session(async_engine):
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(route_session: AsyncSession):
    configure = Permission(id=uuid.uuid4(), code="designer.subject_phase.configure")
    read = Permission(id=uuid.uuid4(), code="designer.subject_phase.read")
    designer_role = Role(
        id=uuid.uuid4(), name="Designer_Role", scope_level="system", is_system=True
    )
    designer = User(
        id=uuid.uuid4(),
        email="designer@example.test",
        password_hash=hash_password("pw"),
        first_name="De",
        last_name="Signer",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    outsider = User(
        id=uuid.uuid4(),
        email="outsider@example.test",
        password_hash=hash_password("pw"),
        first_name="Out",
        last_name="Sider",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    route_session.add_all([configure, read, designer_role, designer, outsider])
    await route_session.flush()
    route_session.add_all(
        [
            RolePermission(role_id=designer_role.id, permission_id=configure.id),
            RolePermission(role_id=designer_role.id, permission_id=read.id),
            UserRole(user_id=designer.id, role_id=designer_role.id),
        ]
    )
    study = Study(
        id=uuid.uuid4(),
        study_code="SP-001",
        title="Phase Study",
        status=StudyStatus.active,
        created_by=designer.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
        created_at=datetime.now(UTC),
    )
    route_session.add_all([study, version])
    await route_session.flush()
    await route_session.commit()
    return {"designer": designer, "outsider": outsider, "version": version}


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


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


class TestRouteAuthorization:
    async def test_get_requires_read_permission(self, client, seeded):
        version_id = seeded["version"].id
        denied = await client.get(
            f"/api/v1/designer/versions/{version_id}/subject-phase-transitions",
            headers=_auth(seeded["outsider"]),
        )
        assert denied.status_code == 403

        ok = await client.get(
            f"/api/v1/designer/versions/{version_id}/subject-phase-transitions",
            headers=_auth(seeded["designer"]),
        )
        assert ok.status_code == 200
        assert ok.json() == []

    async def test_post_and_delete_require_configure(self, client, seeded, route_session):
        version_id = seeded["version"].id

        # Seed two phases via the service against the route session.
        a = await _make_phase(route_session, seeded["version"], "Screening", 1)
        b = await _make_phase(route_session, seeded["version"], "Treatment", 2)
        await route_session.commit()

        body = {"from_phase_id": str(a.id), "to_phase_id": str(b.id)}

        denied = await client.post(
            f"/api/v1/designer/versions/{version_id}/subject-phase-transitions",
            json=body,
            headers=_auth(seeded["outsider"]),
        )
        assert denied.status_code == 403

        created = await client.post(
            f"/api/v1/designer/versions/{version_id}/subject-phase-transitions",
            json=body,
            headers=_auth(seeded["designer"]),
        )
        assert created.status_code == 201
        transition_id = created.json()["id"]

        denied_delete = await client.delete(
            f"/api/v1/designer/versions/{version_id}/subject-phase-transitions/{transition_id}",
            headers=_auth(seeded["outsider"]),
        )
        assert denied_delete.status_code == 403

        ok_delete = await client.delete(
            f"/api/v1/designer/versions/{version_id}/subject-phase-transitions/{transition_id}",
            headers=_auth(seeded["designer"]),
        )
        assert ok_delete.status_code == 204
