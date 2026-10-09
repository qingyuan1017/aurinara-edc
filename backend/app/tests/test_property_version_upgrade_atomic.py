"""Property test for atomic/complete version-upgrade rebind (task 15.3).

# Feature: designer-edc-refactor, Property 11: Version upgrade rebind is atomic and complete

Validates Requirements:
  - 8.3: A Version Upgrade rebinds every affected Operational_Record to the
         newer published Design_Version and records the upgrade in the
         Audit_Service.
  - 8.15: A failed Version Upgrade leaves the affected Operational_Records bound
         to their prior Design_Version, records the failed attempt in the
         Audit_Service, and returns an error indication.

Strategy. For all subjects with a varied operational-record graph (random
counts of visit instances, form instances, field values, form records, review
rows, queries, and polymorphic sdv/lock/signature rows) and a random
success/failure injection, the rebind must be ATOMIC and COMPLETE:

  * On SUCCESS — every affected row (``subject.study_version_id`` plus every
    ``design_version_id`` across visit_instances, form_instances, field_values,
    form_records, review_status, queries, sdv_status, freezes_locks, and
    signatures) moves to the target version; none is left on the prior version
    (COMPLETE); the upgrade is audited exactly once; and an unrelated subject's
    rows are untouched.
  * On FAILURE (injected mid-rebind by wrapping ``_update_rows`` as the unit
    test does) — no affected row is left partially rebound; every affected row
    remains on its prior version (ATOMIC all-or-nothing rollback); the failed
    attempt is audited; and a ``BusinessRuleError`` is raised.

The test uses the in-memory SQLite async-engine pattern from
``test_version_upgrade_service.py``. The engine is built inside the test body
(not a function-scoped fixture) so every Hypothesis example runs against a
fresh, isolated database. Hypothesis runs ≥100 examples with ``deadline=None``
because DB-backed examples are individually slow; per-example graphs are kept
small to bound total runtime.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import BusinessRuleError
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
# Graph-shape strategy
# ---------------------------------------------------------------------------

# A graph shape describes how many of each operational row to seed for one
# subject. Counts are kept small so a DB-backed Hypothesis example stays fast
# while still varying across the full set of design-version-bound tables.
graph_shape = st.fixed_dictionaries(
    {
        "visits": st.integers(min_value=0, max_value=3),
        "forms_per_visit": st.integers(min_value=0, max_value=2),
        "fields_per_form": st.integers(min_value=0, max_value=2),
        "records_per_form": st.integers(min_value=0, max_value=2),
        "queries": st.integers(min_value=0, max_value=3),
        # Polymorphic rows: whether to seed subject-scoped sdv/lock/signature.
        "sdv_subject": st.booleans(),
        "lock_subject": st.booleans(),
        "signature_subject": st.booleans(),
    }
)


# ---------------------------------------------------------------------------
# Operational-record binding columns to assert over (COMPLETE invariant).
# ---------------------------------------------------------------------------

_BINDING_COLUMNS = (
    (VisitInstance, VisitInstance.design_version_id),
    (FormInstance, FormInstance.design_version_id),
    (FieldValue, FieldValue.design_version_id),
    (FormRecord, FormRecord.design_version_id),
    (ReviewStatus, ReviewStatus.design_version_id),
    (Query, Query.design_version_id),
    (SDVStatus, SDVStatus.design_version_id),
    (FreezeLock, FreezeLock.design_version_id),
    (Signature, Signature.design_version_id),
)


async def _make_published_version(
    session: AsyncSession, study_id: uuid.UUID, version_number: str
) -> StudyVersion:
    """Create a *published* Design_Version carrying one form + field.

    The consumption contract's published-only guard (``get_published_design``)
    requires the version to resolve, so each version carries a minimal
    form/section/field graph.
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
        form_code=f"DM-{version_number}-{uuid.uuid4().hex[:4]}",
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


async def _seed_graph(session: AsyncSession, shape: dict) -> dict:
    """Seed a study, two published versions, a site, and a subject graph on v1.

    The ``shape`` dict controls the per-table row counts so the rebind coverage
    varies across examples. A second ("other") subject bound to v1 is always
    seeded as a control: its rows must never be rebound.
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

    # --- Visit / form / field / record / review graph -------------------
    for v in range(shape["visits"]):
        visit = VisitInstance(
            subject_id=subject.id,
            design_version_id=v1.id,
            name=f"Visit {v}",
            status=VisitInstanceStatus.scheduled,
        )
        session.add(visit)
        await session.flush()

        for _f in range(shape["forms_per_visit"]):
            form_instance = FormInstance(
                subject_id=subject.id,
                visit_instance_id=visit.id,
                form_definition_id=uuid.uuid4(),
                design_version_id=v1.id,
                status=FormInstanceStatus.in_progress,
            )
            session.add(form_instance)
            await session.flush()

            for fld in range(shape["fields_per_form"]):
                session.add(
                    FieldValue(
                        form_instance_id=form_instance.id,
                        field_definition_id=uuid.uuid4(),
                        design_version_id=v1.id,
                        value=str(fld),
                    )
                )
            for r in range(shape["records_per_form"]):
                session.add(
                    FormRecord(
                        form_instance_id=form_instance.id,
                        design_version_id=v1.id,
                        sequence_number=r + 1,
                        data_jsonb={"n": r},
                    )
                )
            # Exactly one review row per form instance (unique constraint).
            session.add(
                ReviewStatus(
                    form_instance_id=form_instance.id,
                    design_version_id=v1.id,
                    is_reviewed=False,
                )
            )
            await session.flush()

    for q in range(shape["queries"]):
        session.add(
            Query(
                study_id=study.id,
                site_id=site.id,
                subject_id=subject.id,
                design_version_id=v1.id,
                target_type=QueryTargetType.subject,
                target_id=subject.id,
                text=f"Query {q}",
                query_type=QueryType.manual,
                status=QueryStatus.open,
                created_by=actor,
            )
        )

    # --- Polymorphic subject-scoped rows --------------------------------
    if shape["sdv_subject"]:
        session.add(
            SDVStatus(
                scope_type="subject",
                scope_id=subject.id,
                design_version_id=v1.id,
                is_verified=False,
            )
        )
    if shape["lock_subject"]:
        session.add(
            FreezeLock(
                object_type="subject",
                object_id=subject.id,
                design_version_id=v1.id,
                lock_type="freeze",
                is_active=True,
                locked_by=actor,
            )
        )
    if shape["signature_subject"]:
        session.add(
            Signature(
                object_type="subject",
                object_id=subject.id,
                design_version_id=v1.id,
                signed_by=actor,
                signature_meaning="I attest",
                data_hash=uuid.uuid4().hex,
                status=SignatureStatus.valid,
            )
        )

    # --- Control: a second subject that must never be rebound -----------
    other = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=v1.id,
        subject_number="101-0002",
        status=SubjectStatus.enrolled,
        created_by=actor,
    )
    session.add(other)
    await session.flush()
    other_visit = VisitInstance(
        subject_id=other.id,
        design_version_id=v1.id,
        name="Other visit",
        status=VisitInstanceStatus.scheduled,
    )
    session.add(other_visit)
    # Control SDV row for a different subject (never rebound).
    session.add(
        SDVStatus(
            scope_type="subject",
            scope_id=other.id,
            design_version_id=v1.id,
            is_verified=False,
        )
    )

    await session.commit()
    return {
        "actor": actor,
        "study_id": study.id,
        "site_id": site.id,
        "subject_id": subject.id,
        "other_subject_id": other.id,
        "other_visit_id": other_visit.id,
        "v1": v1.id,
        "v2": v2.id,
    }


async def _count_on_version(
    session: AsyncSession, model, column, version_id: uuid.UUID
) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(model).where(column == version_id)
        )
    ).scalar_one()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(shape=graph_shape, inject_failure=st.booleans())
async def test_version_upgrade_rebind_is_atomic_and_complete(shape, inject_failure):
    """Rebind is all-or-nothing and complete across varied graphs (R8.3, R8.15)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401  (register every ORM table)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        async with factory() as seed:
            ids = await _seed_graph(seed, shape)

        service = VersionUpgradeService()

        if inject_failure:
            # Force a failure after the first UPDATE (subject's own binding),
            # mirroring the unit test's mid-rebind injection via _update_rows.
            real_update_rows = service._update_rows
            state = {"n": 0}

            async def failing_update_rows(session, stmt):
                state["n"] += 1
                if state["n"] >= 2:
                    raise RuntimeError("simulated rebind failure")
                return await real_update_rows(session, stmt)

            service._update_rows = failing_update_rows  # type: ignore[method-assign]

        async with factory() as session:
            if inject_failure:
                with pytest.raises(BusinessRuleError):
                    await service.upgrade_subject(
                        session,
                        subject_id=ids["subject_id"],
                        target_design_version_id=ids["v2"],
                        actor_id=ids["actor"],
                    )
                # Mirror the route's get_db rollback-on-error; the service has
                # already committed the failure audit and reverted the rebind.
                await session.rollback()
            else:
                result = await service.upgrade_subject(
                    session,
                    subject_id=ids["subject_id"],
                    target_design_version_id=ids["v2"],
                    actor_id=ids["actor"],
                )
                await session.commit()
                assert result["from_design_version_id"] == ids["v1"]
                assert result["to_design_version_id"] == ids["v2"]

        # ---- Verify the invariant ----------------------------------------
        async with factory() as check:
            subject = await check.get(Subject, ids["subject_id"])

            if inject_failure:
                # ATOMIC: nothing partially rebound — everything stays on v1.
                assert subject.study_version_id == ids["v1"]
                for model, column in _BINDING_COLUMNS:
                    on_v2 = await _count_on_version(check, model, column, ids["v2"])
                    assert on_v2 == 0, f"{model.__name__} partially rebound to v2"

                # No success audit; exactly one failed-attempt audit (R8.15).
                success = (
                    await check.execute(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == "version_upgrade")
                    )
                ).scalar_one()
                assert success == 0
                failures = (
                    await check.execute(
                        select(AuditEvent).where(
                            AuditEvent.action == "version_upgrade_failed"
                        )
                    )
                ).scalars().all()
                assert len(failures) == 1
                assert failures[0].entity_id == ids["subject_id"]
                assert failures[0].new_value == str(ids["v2"])
            else:
                # COMPLETE: subject + every affected row moved to v2, none on v1.
                # The control subject's rows (visit + sdv) stay on v1, so the
                # completeness check is scoped to the upgraded subject's own
                # graph (see _subject_rows_on_version) rather than a global
                # v1 row count.
                assert subject.study_version_id == ids["v2"]

                # Subject-scoped completeness: no v1 rows remain for the subject.
                remaining_v1 = await _subject_rows_on_version(
                    check, ids, ids["v1"]
                )
                assert remaining_v1 == 0, "upgrade left subject rows on prior version"

                # Exactly one success audit, no failure audit (R8.3).
                success = (
                    await check.execute(
                        select(AuditEvent).where(
                            AuditEvent.action == "version_upgrade",
                            AuditEvent.entity_type == "subject",
                        )
                    )
                ).scalars().all()
                assert len(success) == 1
                assert success[0].old_value == str(ids["v1"])
                assert success[0].new_value == str(ids["v2"])
                assert success[0].subject_id == ids["subject_id"]
                failures = (
                    await check.execute(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == "version_upgrade_failed")
                    )
                ).scalar_one()
                assert failures == 0

            # The control subject is NEVER rebound, in either path.
            other = await check.get(Subject, ids["other_subject_id"])
            assert other.study_version_id == ids["v1"]
            other_visit = await check.get(VisitInstance, ids["other_visit_id"])
            assert other_visit.design_version_id == ids["v1"]
            other_sdv_on_v2 = (
                await check.execute(
                    select(func.count())
                    .select_from(SDVStatus)
                    .where(
                        SDVStatus.scope_type == "subject",
                        SDVStatus.scope_id == ids["other_subject_id"],
                        SDVStatus.design_version_id == ids["v2"],
                    )
                )
            ).scalar_one()
            assert other_sdv_on_v2 == 0
    finally:
        await engine.dispose()


async def _subject_rows_on_version(
    session: AsyncSession, ids: dict, version_id: uuid.UUID
) -> int:
    """Count the upgraded subject's operational rows still on ``version_id``.

    Covers every design-version-bound table scoped (directly or transitively)
    to the upgraded subject, including the polymorphic sdv/lock/signature rows.
    """
    subject_id = ids["subject_id"]

    visit_ids = list(
        (
            await session.execute(
                select(VisitInstance.id).where(
                    VisitInstance.subject_id == subject_id
                )
            )
        ).scalars()
    )
    form_ids = list(
        (
            await session.execute(
                select(FormInstance.id).where(
                    FormInstance.subject_id == subject_id
                )
            )
        ).scalars()
    )
    field_ids = (
        list(
            (
                await session.execute(
                    select(FieldValue.id).where(
                        FieldValue.form_instance_id.in_(form_ids)
                    )
                )
            ).scalars()
        )
        if form_ids
        else []
    )

    total = 0
    total += (
        await session.execute(
            select(func.count())
            .select_from(VisitInstance)
            .where(
                VisitInstance.subject_id == subject_id,
                VisitInstance.design_version_id == version_id,
            )
        )
    ).scalar_one()
    total += (
        await session.execute(
            select(func.count())
            .select_from(FormInstance)
            .where(
                FormInstance.subject_id == subject_id,
                FormInstance.design_version_id == version_id,
            )
        )
    ).scalar_one()
    total += (
        await session.execute(
            select(func.count())
            .select_from(Query)
            .where(
                Query.subject_id == subject_id,
                Query.design_version_id == version_id,
            )
        )
    ).scalar_one()
    if form_ids:
        for model in (FieldValue, FormRecord, ReviewStatus):
            total += (
                await session.execute(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.form_instance_id.in_(form_ids),
                        model.design_version_id == version_id,
                    )
                )
            ).scalar_one()

    # Polymorphic rows scoped to the subject's own object graph.
    def _poly_count(model, type_col, id_col):
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.design_version_id == version_id)
        )
        # Build (type, id) membership for the subject's full graph.
        conds = [and_(type_col == "subject", id_col == subject_id)]
        if visit_ids:
            conds.append(and_(type_col == "visit", id_col.in_(visit_ids)))
        if form_ids:
            conds.append(and_(type_col == "form", id_col.in_(form_ids)))
        if field_ids:
            conds.append(and_(type_col == "field", id_col.in_(field_ids)))
        return stmt.where(or_(*conds))

    for model, type_col, id_col in (
        (SDVStatus, SDVStatus.scope_type, SDVStatus.scope_id),
        (FreezeLock, FreezeLock.object_type, FreezeLock.object_id),
        (Signature, Signature.object_type, Signature.object_id),
    ):
        total += (
            await session.execute(_poly_count(model, type_col, id_col))
        ).scalar_one()

    return total
