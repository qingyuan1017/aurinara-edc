"""Unit tests for the VersionUpgradeService (task 15.2).

Validates Requirements:
  - 8.3: A Version Upgrade rebinds every affected Operational_Record to the
         newer published Design_Version and records the upgrade in the
         Audit_Service.
  - 8.15: A failed Version Upgrade leaves the affected Operational_Records bound
         to their prior Design_Version, records the failed attempt in the
         Audit_Service, and returns an error.

These are integration-style unit tests against a real in-memory SQLite database
(following the engine/seed pattern used across the EDC/designer service tests)
because the behaviour under test is transactional: a SAVEPOINT-scoped rebind,
an all-or-nothing rollback on failure, and a failure audit that survives the
data rollback. A mocked session cannot exercise those semantics faithfully.
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
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.edc.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.edc.form_record import FormRecord
from app.models.edc.lock import FreezeLock
from app.models.edc.query import Query, QueryStatus, QueryTargetType, QueryType
from app.models.edc.review import ReviewStatus
from app.models.edc.sdv import SDVStatus
from app.models.edc.signature import Signature, SignatureStatus
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import Study, StudyStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.models.shared.audit import AuditEvent
from app.services.edc.version_upgrade_service import VersionUpgradeService

# ---------------------------------------------------------------------------
# Engine / session fixtures
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


async def _make_published_version(
    session: AsyncSession, study_id: uuid.UUID, version_number: str
) -> StudyVersion:
    """Create a *published* Design_Version carrying one form + field.

    The consumption contract requires a form/field so ``get_published_design``
    (the published-only guard used by the service) resolves successfully.
    """
    version = StudyVersion(
        study_id=study_id,
        version_number=version_number,
        status=StudyVersionStatus.published,
    )
    session.add(version)
    await session.flush()

    form = FormDefinition(
        study_version_id=version.id,
        name="Demographics",
        form_code=f"DM-{version_number}",
        display_order=1,
        is_repeating=True,
    )
    session.add(form)
    await session.flush()
    section = FormSection(
        form_definition_id=form.id, name="Basics", display_order=1
    )
    session.add(section)
    await session.flush()
    session.add(
        FieldDefinition(
            form_section_id=section.id,
            label="Age",
            variable_name="age",
            control_type="integer",
            data_type="integer",
            is_required=True,
            display_order=1,
        )
    )
    await session.flush()
    return version


async def _seed_subject_graph(session: AsyncSession) -> dict:
    """Seed a study, two published versions, a site, and a fully-populated subject.

    Every operational table that carries a design-version binding gets at least
    one row bound to ``v1`` so the rebind coverage is observable.
    """
    actor = uuid.uuid4()
    study = Study(
        study_code=f"ST-{uuid.uuid4().hex[:8]}",
        title="Upgrade Study",
        status=StudyStatus.active,
        created_by=actor,
    )
    session.add(study)
    await session.flush()

    v1 = await _make_published_version(session, study.id, "1.0")
    v2 = await _make_published_version(session, study.id, "2.0")

    site = Site(
        study_id=study.id,
        site_number="101",
        name="Site 101",
        status=SiteStatus.active,
    )
    session.add(site)
    await session.flush()

    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=v1.id,
        subject_number="101-0001",
        status=SubjectStatus.enrolled,
        created_by=actor,
    )
    session.add(subject)
    await session.flush()

    visit = VisitInstance(
        subject_id=subject.id,
        design_version_id=v1.id,
        name="Screening",
        status=VisitInstanceStatus.scheduled,
    )
    session.add(visit)
    await session.flush()

    form_instance = FormInstance(
        subject_id=subject.id,
        visit_instance_id=visit.id,
        form_definition_id=uuid.uuid4(),
        design_version_id=v1.id,
        status=FormInstanceStatus.in_progress,
    )
    session.add(form_instance)
    await session.flush()

    field_value = FieldValue(
        form_instance_id=form_instance.id,
        field_definition_id=uuid.uuid4(),
        design_version_id=v1.id,
        value="42",
    )
    session.add(field_value)
    form_record = FormRecord(
        form_instance_id=form_instance.id,
        design_version_id=v1.id,
        sequence_number=1,
        data_jsonb={"age": 42},
    )
    session.add(form_record)
    review = ReviewStatus(
        form_instance_id=form_instance.id,
        design_version_id=v1.id,
        is_reviewed=False,
    )
    session.add(review)
    query = Query(
        study_id=study.id,
        site_id=site.id,
        subject_id=subject.id,
        design_version_id=v1.id,
        target_type=QueryTargetType.subject,
        target_id=subject.id,
        text="Please confirm age",
        query_type=QueryType.manual,
        status=QueryStatus.open,
        created_by=actor,
    )
    session.add(query)
    await session.flush()

    # Polymorphic tables scoped to the subject's object graph.
    sdv = SDVStatus(
        scope_type="subject",
        scope_id=subject.id,
        design_version_id=v1.id,
        is_verified=False,
    )
    session.add(sdv)
    sdv_field = SDVStatus(
        scope_type="field",
        scope_id=field_value.id,
        design_version_id=v1.id,
        is_verified=True,
    )
    session.add(sdv_field)
    lock = FreezeLock(
        object_type="subject",
        object_id=subject.id,
        design_version_id=v1.id,
        lock_type="freeze",
        is_active=True,
        locked_by=actor,
    )
    session.add(lock)
    signature = Signature(
        object_type="form",
        object_id=form_instance.id,
        design_version_id=v1.id,
        signed_by=actor,
        signature_meaning="I attest",
        data_hash="abc123",
        status=SignatureStatus.valid,
    )
    session.add(signature)

    # A control row that must NOT be rebound: a different subject's SDV row.
    other_sdv = SDVStatus(
        scope_type="subject",
        scope_id=uuid.uuid4(),
        design_version_id=v1.id,
        is_verified=False,
    )
    session.add(other_sdv)

    await session.commit()
    return {
        "actor": actor,
        "study_id": study.id,
        "site_id": site.id,
        "subject_id": subject.id,
        "v1": v1.id,
        "v2": v2.id,
        "other_sdv_id": other_sdv.id,
    }


# ---------------------------------------------------------------------------
# Success path (R8.3)
# ---------------------------------------------------------------------------


class TestUpgradeSubjectSuccess:
    async def test_rebinds_all_records_and_audits_upgrade(self, session_factory):
        """All affected records move to v2 and the upgrade is audited (R8.3)."""
        async with session_factory() as seed:
            ids = await _seed_subject_graph(seed)

        service = VersionUpgradeService()
        async with session_factory() as session:
            result = await service.upgrade_subject(
                session,
                subject_id=ids["subject_id"],
                target_design_version_id=ids["v2"],
                actor_id=ids["actor"],
            )
            await session.commit()

        assert result["from_design_version_id"] == ids["v1"]
        assert result["to_design_version_id"] == ids["v2"]
        assert result["rebound_total"] > 0

        async with session_factory() as check:
            subject = await check.get(Subject, ids["subject_id"])
            assert subject.study_version_id == ids["v2"]

            # Every operational row for the subject now points at v2.
            for model, column in (
                (VisitInstance, VisitInstance.design_version_id),
                (FormInstance, FormInstance.design_version_id),
                (FieldValue, FieldValue.design_version_id),
                (FormRecord, FormRecord.design_version_id),
                (ReviewStatus, ReviewStatus.design_version_id),
                (Query, Query.design_version_id),
            ):
                still_on_v1 = (
                    await check.execute(
                        select(func.count())
                        .select_from(model)
                        .where(column == ids["v1"])
                    )
                ).scalar_one()
                assert still_on_v1 == 0, f"{model.__name__} not fully rebound"

            # Polymorphic subject-scoped rows rebound; the other subject's row stays.
            subj_sdv = (
                await check.execute(
                    select(SDVStatus).where(SDVStatus.scope_type == "subject")
                )
            ).scalars().all()
            for row in subj_sdv:
                if row.id == ids["other_sdv_id"]:
                    assert row.design_version_id == ids["v1"]
                else:
                    assert row.design_version_id == ids["v2"]

            lock = (
                await check.execute(select(FreezeLock))
            ).scalars().first()
            assert lock.design_version_id == ids["v2"]
            sig = (await check.execute(select(Signature))).scalars().first()
            assert sig.design_version_id == ids["v2"]

            # Exactly one success audit event records the upgrade (R8.3).
            upgrade_events = (
                await check.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "version_upgrade",
                        AuditEvent.entity_type == "subject",
                    )
                )
            ).scalars().all()
            assert len(upgrade_events) == 1
            event = upgrade_events[0]
            assert event.old_value == str(ids["v1"])
            assert event.new_value == str(ids["v2"])
            assert event.subject_id == ids["subject_id"]

    async def test_rejects_draft_target(self, session_factory):
        """A draft target version is rejected before any mutation (R8.3)."""
        async with session_factory() as seed:
            ids = await _seed_subject_graph(seed)
            draft = StudyVersion(
                study_id=ids["study_id"],
                version_number="3.0",
                status=StudyVersionStatus.draft,
            )
            seed.add(draft)
            await seed.flush()
            draft_id = draft.id
            await seed.commit()

        service = VersionUpgradeService()
        async with session_factory() as session:
            with pytest.raises(ValidationError):
                await service.upgrade_subject(
                    session,
                    subject_id=ids["subject_id"],
                    target_design_version_id=draft_id,
                    actor_id=ids["actor"],
                )

        async with session_factory() as check:
            subject = await check.get(Subject, ids["subject_id"])
            assert subject.study_version_id == ids["v1"]  # unchanged

    async def test_rejects_missing_target(self, session_factory):
        """A missing target version is rejected (R8.3)."""
        async with session_factory() as seed:
            ids = await _seed_subject_graph(seed)

        service = VersionUpgradeService()
        async with session_factory() as session:
            with pytest.raises(NotFoundError):
                await service.upgrade_subject(
                    session,
                    subject_id=ids["subject_id"],
                    target_design_version_id=uuid.uuid4(),
                    actor_id=ids["actor"],
                )

    async def test_rejects_target_from_other_study(self, session_factory):
        """A published target of a different study is rejected (R8.3)."""
        async with session_factory() as seed:
            ids = await _seed_subject_graph(seed)
            other_study = Study(
                study_code=f"ST-{uuid.uuid4().hex[:8]}",
                title="Other Study",
                status=StudyStatus.active,
                created_by=ids["actor"],
            )
            seed.add(other_study)
            await seed.flush()
            foreign = await _make_published_version(seed, other_study.id, "1.0")
            foreign_id = foreign.id
            await seed.commit()

        service = VersionUpgradeService()
        async with session_factory() as session:
            with pytest.raises(ValidationError):
                await service.upgrade_subject(
                    session,
                    subject_id=ids["subject_id"],
                    target_design_version_id=foreign_id,
                    actor_id=ids["actor"],
                )


# ---------------------------------------------------------------------------
# Failure path (R8.15)
# ---------------------------------------------------------------------------


class TestUpgradeSubjectFailure:
    async def test_failure_leaves_prior_version_and_audits_attempt(
        self, session_factory, monkeypatch
    ):
        """On failure, records stay on v1 and the failed attempt is audited (R8.15).

        The rebind is forced to raise after mutating some rows (inside the
        SAVEPOINT). The service must roll back the SAVEPOINT so every affected
        record remains on its prior version, persist a durable failure audit on
        a separate transaction, and raise a BusinessRuleError.
        """
        async with session_factory() as seed:
            ids = await _seed_subject_graph(seed)

        service = VersionUpgradeService()

        # Force a failure partway through the rebind: wrap the real _update_rows
        # so it performs the subject + visit updates, then raises.
        real_update_rows = service._update_rows
        call_state = {"count": 0}

        async def failing_update_rows(session, stmt):
            call_state["count"] += 1
            # Allow the first two UPDATEs (subject + visit_instances) to run,
            # then raise to simulate a mid-rebind failure.
            if call_state["count"] >= 3:
                raise RuntimeError("simulated rebind failure")
            return await real_update_rows(session, stmt)

        monkeypatch.setattr(service, "_update_rows", failing_update_rows)

        async with session_factory() as session:
            with pytest.raises(BusinessRuleError):
                await service.upgrade_subject(
                    session,
                    subject_id=ids["subject_id"],
                    target_design_version_id=ids["v2"],
                    actor_id=ids["actor"],
                )
            # Mirror the route's get_db: it attempts a rollback when the error
            # propagates. The service already committed the failure audit (and
            # the SAVEPOINT already reverted the rebind), so this is a no-op and
            # must not undo the durable failure audit.
            await session.rollback()

        async with session_factory() as check:
            # Every affected record remains on the prior version (R8.15).
            subject = await check.get(Subject, ids["subject_id"])
            assert subject.study_version_id == ids["v1"]
            visit_on_v2 = (
                await check.execute(
                    select(func.count())
                    .select_from(VisitInstance)
                    .where(VisitInstance.design_version_id == ids["v2"])
                )
            ).scalar_one()
            assert visit_on_v2 == 0

            # No success audit was written.
            success_events = (
                await check.execute(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "version_upgrade")
                )
            ).scalar_one()
            assert success_events == 0

            # The failed attempt was audited and survived the data rollback.
            failure_events = (
                await check.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "version_upgrade_failed"
                    )
                )
            ).scalars().all()
            assert len(failure_events) == 1
            assert failure_events[0].entity_id == ids["subject_id"]
            assert failure_events[0].new_value == str(ids["v2"])
