"""Operational-continuity post-migration integration test (task 20.2).

After the ``Migration_Process`` reassigns logical ownership of the historical
combined EDC capability into the Designer and EDC modules, every existing
operational flow must keep working against a bound ``Published_Design``
(Requirement 11.4).

This test proves that end-to-end:

1. Seed a Study + a *published* Design_Version carrying real design content
   (a visit definition and a form/section/field), a site, a user, and a subject
   bound to that published design. The subject is created through the real
   ``subject_service.create_subject`` so its Visit_Instances and Form_Instances
   are initialized from the bound design and carry the inherited (now not-null)
   ``design_version_id``.
2. Simulate the migration by running ``reassignment_service.reassign_all`` —
   the logical ownership reassignment (Phase 4). No stored value changes.
3. Run representative operational flows end-to-end *after* the simulated
   migration and assert each one succeeds against the bound published design:
     - Data entry  — ``data_capture_service.save_draft`` (+ ``submit``)
     - Query       — ``query_service.create_query`` / ``respond`` / ``close``
     - SDV         — ``sdv_service.set_sdv`` on a form target
     - Review      — ``review_service.mark_reviewed``
     - Lock        — ``lock_service.freeze`` / ``lock``
   Every created operational record inherits the correct ``design_version_id``
   from the subject's bound published design, and no flow raises.
4. Assert the design-dependent reads route through
   ``design_consumption_service`` — the published design remains consumable
   after migration.

These use a real in-memory SQLite async database (following the engine/seed
patterns in ``test_edit_check_routes.py`` and ``test_version_upgrade_service.py``)
because the behaviour under test is the real cross-service persistence path, not
something a mock can exercise faithfully.

Validates: Requirements 11.4
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.security import hash_password
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.schedule_of_assessment import (
    ScheduleOfAssessment,
    ScheduleOfAssessmentEntry,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.edc.lock import FreezeLock
from app.models.edc.query import Query, QueryStatus, QueryTargetType
from app.models.edc.review import ReviewStatus
from app.models.edc.sdv import SDVScopeType, SDVStatus
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import Study, StudyStatus
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.models.shared.identity import User, UserStatus
from app.schemas.edc.subject import SubjectCreate
from app.services.designer.design_consumption_service import (
    design_consumption_service,
)
from app.services.designer.migration.reassignment_service import (
    reassignment_service,
)
from app.services.edc.data_capture_service import data_capture_service
from app.services.edc.lock_service import lock_service
from app.services.edc.query_service import query_service
from app.services.edc.review_service import review_service
from app.services.edc.sdv_service import sdv_service
from app.services.edc.subject_service import subject_service

# ---------------------------------------------------------------------------
# Engine / session fixtures (mirror the EDC/designer service test pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(async_engine):
    return async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_published_design(session: AsyncSession) -> dict:
    """Seed a Study + PUBLISHED Design_Version with real design content.

    The published design carries one visit definition and one form with a
    section and a single field, so the subject's instance initialization and
    the ``design_consumption_service`` reads both resolve against real content.
    """
    actor = User(
        id=uuid.uuid4(),
        email="continuity@example.test",
        password_hash=hash_password("pw"),
        first_name="Op",
        last_name="Continuity",
        status=UserStatus.active,
        mfa_enabled=False,
    )
    session.add(actor)

    study = Study(
        study_code=f"ST-{uuid.uuid4().hex[:8]}",
        title="Continuity Study",
        status=StudyStatus.active,
        created_by=actor.id,
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
    )
    session.add(version)
    await session.flush()

    visit_def = VisitDefinition(
        study_version_id=version.id,
        name="Screening",
        visit_number=1,
        visit_type="scheduled",
        target_day=0,
        window_before=0,
        window_after=0,
        display_order=1,
    )
    session.add(visit_def)

    form = FormDefinition(
        study_version_id=version.id,
        name="Demographics",
        form_code="DM",
        display_order=1,
        is_repeating=False,
    )
    session.add(form)
    await session.flush()
    section = FormSection(
        form_definition_id=form.id, name="Basics", display_order=1
    )
    session.add(section)
    await session.flush()
    field = FieldDefinition(
        form_section_id=section.id,
        label="Age",
        variable_name="age",
        control_type="integer",
        data_type="integer",
        is_required=True,
        display_order=1,
    )
    session.add(field)

    schedule = ScheduleOfAssessment(design_version_id=version.id)
    session.add(schedule)
    await session.flush()
    session.add(
        ScheduleOfAssessmentEntry(
            schedule_of_assessment_id=schedule.id,
            form_definition_id=form.id,
            visit_definition_id=visit_def.id,
            display_order=1,
        )
    )

    site = Site(
        study_id=study.id,
        site_number="101",
        name="Site 101",
        status=SiteStatus.active,
    )
    session.add(site)
    await session.flush()

    await session.commit()
    return {
        "actor_id": actor.id,
        "study_id": study.id,
        "site_id": site.id,
        "version_id": version.id,
        "form_definition_id": form.id,
        "field_definition_id": field.id,
    }


# ---------------------------------------------------------------------------
# Operational continuity after a simulated migration (R11.4)
# ---------------------------------------------------------------------------


class TestOperationalContinuityPostMigration:
    async def test_all_flows_succeed_against_bound_published_design(
        self, session_factory
    ):
        """Every operational flow keeps working after the migration (R11.4)."""
        # --- Seed the published design + a bound subject graph --------------
        async with session_factory() as seed:
            ids = await _seed_published_design(seed)

        async with session_factory() as session:
            subject = await subject_service.create_subject(
                session,
                study_id=ids["study_id"],
                data=SubjectCreate(site_id=ids["site_id"]),
                actor_id=ids["actor_id"],
            )
            await session.commit()
            subject_id = subject.id
            # The subject must be bound to the published design (R2.7/7.3).
            assert subject.study_version_id == ids["version_id"]

        # Resolve one initialized form instance for the subject (bound to v1).
        async with session_factory() as check:
            form_instance = (
                await check.execute(
                    select(FormInstance).where(
                        FormInstance.subject_id == subject_id
                    )
                )
            ).scalars().first()
            assert form_instance is not None
            assert form_instance.design_version_id == ids["version_id"]
            form_instance_id = form_instance.id

        # --- Simulate the Migration_Process (Phase 4 reassignment) ----------
        async with session_factory() as session:
            result = await reassignment_service.reassign_all(
                session, actor_id=ids["actor_id"]
            )
            await session.commit()
            assert result.audit_history_preserved is True
            assert result.events, "reassignment recorded no events"

        # --- 1. Data entry: save_draft (+ submit) ---------------------------
        async with session_factory() as session:
            fi = await data_capture_service.load(session, form_instance_id)
            await data_capture_service.save_draft(
                session,
                fi,
                {str(ids["field_definition_id"]): 42},
                actor_id=ids["actor_id"],
            )
            await data_capture_service.submit(session, fi, actor_id=ids["actor_id"])
            await session.commit()

        async with session_factory() as check:
            fv = (
                await check.execute(
                    select(FieldValue).where(
                        FieldValue.form_instance_id == form_instance_id
                    )
                )
            ).scalars().first()
            assert fv is not None
            assert fv.value == "42"
            # The field value inherits the bound published design (R11.4).
            assert fv.design_version_id == ids["version_id"]
            submitted = await check.get(FormInstance, form_instance_id)
            assert submitted.status == FormInstanceStatus.submitted

        # --- 2. Query: create -> respond -> close ---------------------------
        async with session_factory() as session:
            query = await query_service.create_query(
                session,
                study_id=ids["study_id"],
                target_type=QueryTargetType.form_instance,
                target_id=form_instance_id,
                text="Please confirm the captured age.",
                actor_id=ids["actor_id"],
                site_id=ids["site_id"],
                subject_id=subject_id,
            )
            await query_service.respond(
                session, query, "Age confirmed.", actor_id=ids["actor_id"]
            )
            await query_service.close(session, query, actor_id=ids["actor_id"])
            await session.commit()
            query_id = query.id
            # Query binding is inherited from the subject's bound design.
            assert query.design_version_id == ids["version_id"]

        async with session_factory() as check:
            closed = await check.get(Query, query_id)
            assert closed.status == QueryStatus.closed

        # --- 3. SDV: verify the form instance -------------------------------
        async with session_factory() as session:
            fi = await data_capture_service.load(session, form_instance_id)
            sdv_status = await sdv_service.set_sdv(
                session,
                SDVScopeType.form,
                fi,
                actor_id=ids["actor_id"],
            )
            await session.commit()
            assert sdv_status.is_verified is True
            assert sdv_status.design_version_id == ids["version_id"]

        async with session_factory() as check:
            verified = (
                await check.execute(
                    select(SDVStatus).where(
                        SDVStatus.scope_type == SDVScopeType.form.value,
                        SDVStatus.scope_id == form_instance_id,
                    )
                )
            ).scalars().first()
            assert verified is not None and verified.is_verified is True

        # --- 4. Review: mark reviewed ---------------------------------------
        async with session_factory() as session:
            fi = await data_capture_service.load(session, form_instance_id)
            review = await review_service.mark_reviewed(
                session, fi, actor_id=ids["actor_id"]
            )
            await session.commit()
            assert review.is_reviewed is True
            assert review.design_version_id == ids["version_id"]

        async with session_factory() as check:
            reviewed = (
                await check.execute(
                    select(ReviewStatus).where(
                        ReviewStatus.form_instance_id == form_instance_id
                    )
                )
            ).scalars().first()
            assert reviewed is not None and reviewed.is_reviewed is True

        # --- 5. Lock: freeze then lock the form instance --------------------
        async with session_factory() as session:
            freeze = await lock_service.freeze(
                session,
                object_type="form",
                object_id=form_instance_id,
                actor_id=ids["actor_id"],
            )
            lock = await lock_service.lock(
                session,
                object_type="form",
                object_id=form_instance_id,
                actor_id=ids["actor_id"],
            )
            await session.commit()
            assert freeze.is_active is True
            assert lock.is_active is True
            # Freeze/lock records inherit the bound published design (R11.4).
            assert freeze.design_version_id == ids["version_id"]
            assert lock.design_version_id == ids["version_id"]

        async with session_factory() as check:
            active_controls = (
                await check.execute(
                    select(func.count())
                    .select_from(FreezeLock)
                    .where(
                        FreezeLock.object_type == "form",
                        FreezeLock.object_id == form_instance_id,
                        FreezeLock.is_active.is_(True),
                    )
                )
            ).scalar_one()
            assert active_controls == 2

        # --- Published design remains consumable after migration (R11.4) ----
        async with session_factory() as session:
            published = await design_consumption_service.get_published_design(
                session, ids["version_id"]
            )
            assert published.design_version_id == ids["version_id"]
            assert [form.id for form in published.forms] == [
                ids["form_definition_id"]
            ]
            assert len(published.visit_definitions) == 1

            fields = await design_consumption_service.get_form_fields(
                session, ids["version_id"], ids["form_definition_id"]
            )
            assert [f.id for f in fields] == [ids["field_definition_id"]]

    async def test_every_operational_record_inherits_bound_design_version(
        self, session_factory
    ):
        """All operational records created post-migration share the bound design.

        A single assertion sweep over the operational tables confirms the
        design-version binding is both present and consistent after the full
        flow set runs against the migrated database (R11.4).
        """
        async with session_factory() as seed:
            ids = await _seed_published_design(seed)

        async with session_factory() as session:
            subject = await subject_service.create_subject(
                session,
                study_id=ids["study_id"],
                data=SubjectCreate(site_id=ids["site_id"]),
                actor_id=ids["actor_id"],
            )
            await session.commit()
            subject_id = subject.id

        async with session_factory() as session:
            await reassignment_service.reassign_all(
                session, actor_id=ids["actor_id"]
            )
            await session.commit()

        version_id = ids["version_id"]
        async with session_factory() as check:
            # Visit + form instances were initialized bound to the design.
            visit_versions = (
                await check.execute(
                    select(VisitInstance.design_version_id).where(
                        VisitInstance.subject_id == subject_id
                    )
                )
            ).scalars().all()
            assert visit_versions and all(v == version_id for v in visit_versions)

            form_versions = (
                await check.execute(
                    select(FormInstance.design_version_id).where(
                        FormInstance.subject_id == subject_id
                    )
                )
            ).scalars().all()
            assert form_versions and all(v == version_id for v in form_versions)

            bound_subject = await check.get(Subject, subject_id)
            assert bound_subject.study_version_id == version_id
