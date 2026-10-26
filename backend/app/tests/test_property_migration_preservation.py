"""Property-based test for migration count/value preservation.

**Validates: Requirements 11.1, 11.2, 11.5**

Property 15: Migration preserves record count and values.

Phase 4 of the ``Migration_Process``
(:meth:`~app.services.designer.migration.reassignment_service.ReassignmentService.reassign_all`)
reassigns ownership of every record set from the historical combined EDC
capability to the Designer / EDC modules. It is a **code-layer ownership
change**: it records one immutable audit event per set and NEVER rewrites a
stored value of any design-time (R11.1) or operational (R11.2) record.

This property generates a random, non-trivial database — varied contents across
several design-time sets (studies, study versions, visit/form/section/field
definitions, codelists, codelist items) and operational sets (subjects, visit
instances, form instances, form records, field values), all bound to a
published ``Design_Version`` — then:

1. captures the Phase 0 :class:`MigrationSnapshot` (per-set count + order-
   independent value checksum),
2. runs ``reassign_all`` (Phase 4),
3. asserts post-migration verification is ``ok`` with no failing sets, and that
   EVERY reassigned set's count and value checksum are byte-identical to the
   Phase 0 snapshot (R11.5).

Because reassignment only appends audit events, the record-set counts and
checksums must be preserved exactly; any drift would be a data-loss risk that
:class:`VerificationService` reports (R11.5/R11.6).
"""

# Feature: designer-edc-refactor, Property 15: Migration preserves record count and values

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models
from app.core.database import Base
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.form_record import FormRecord
from app.models.edc.study import Study, StudyStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitInstance
from app.services.designer.migration.reassignment_service import reassignment_service
from app.services.designer.migration.snapshot_service import (
    RECORD_SET_MODELS,
    snapshot_service,
)
from app.services.designer.migration.verification_service import VerificationService

_ACTOR_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
# Fixed timestamp so a seeded row's checksum is deterministic within a run
# (several models default created_at to datetime.now(UTC) at flush time).
_FIXED_TS = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

_FIELD_VALUE_SHAPES = ["72", "mild", "", "yes", "3.14", None]
_SUBJECT_STATUSES = list(SubjectStatus)


@st.composite
def _seed_plan(draw: st.DrawFn) -> dict[str, int]:
    """Generate a plan describing how many rows to seed per operational set.

    The design-time scaffolding (study + published version + one form/section/
    field + one visit definition + one codelist) is always present so the
    published design is consumable; the strategy varies the *operational* record
    counts (and codelist-item count) so the property holds across arbitrary,
    non-trivial databases.
    """
    return {
        "codelist_items": draw(st.integers(min_value=0, max_value=6)),
        "subjects": draw(st.integers(min_value=0, max_value=4)),
        "visit_instances": draw(st.integers(min_value=0, max_value=4)),
        "form_instances": draw(st.integers(min_value=0, max_value=4)),
        "form_records": draw(st.integers(min_value=0, max_value=5)),
        "field_values": draw(st.integers(min_value=0, max_value=8)),
        # Index into _FIELD_VALUE_SHAPES per seeded field value, so stored
        # values vary (including empty string and NULL) across examples.
        "field_value_shapes": draw(
            st.lists(
                st.integers(min_value=0, max_value=len(_FIELD_VALUE_SHAPES) - 1),
                min_size=8,
                max_size=8,
            )
        ),
    }


async def _seed(session: AsyncSession, plan: dict[str, int]) -> uuid.UUID:
    """Seed a published design plus varied operational data; return version id.

    SQLite does not enforce foreign keys by default, so operational rows can be
    bound to the published ``design_version_id`` with synthetic parent ids
    without materializing the full relational tree — the snapshot/verification
    only read counts and stored column values.
    """
    study = Study(
        id=uuid.uuid4(),
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Migration Preservation Study",
        status=StudyStatus.active,
        created_by=_ACTOR_ID,
        created_at=_FIXED_TS,
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=_FIXED_TS,
        published_by=_ACTOR_ID,
        created_at=_FIXED_TS,
    )
    session.add(version)
    await session.flush()

    # Minimal design-time content so the published design is consumable.
    form = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Demographics",
        form_code="DM",
        display_order=1,
        is_repeating=False,
    )
    session.add(form)
    await session.flush()
    section = FormSection(
        id=uuid.uuid4(),
        form_definition_id=form.id,
        name="Basics",
        display_order=1,
    )
    session.add(section)
    await session.flush()
    field = FieldDefinition(
        id=uuid.uuid4(),
        form_section_id=section.id,
        label="Age",
        variable_name="age",
        control_type="integer",
        data_type="integer",
        is_required=True,
        display_order=1,
    )
    session.add(field)
    session.add(
        VisitDefinition(
            id=uuid.uuid4(),
            study_version_id=version.id,
            name="Screening",
            visit_number=1,
            visit_type="scheduled",
            display_order=1,
            is_required=True,
        )
    )

    codelist = Codelist(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Gender",
        code="GENDER",
    )
    session.add(codelist)
    await session.flush()
    for i in range(plan["codelist_items"]):
        session.add(
            CodelistItem(
                id=uuid.uuid4(),
                codelist_id=codelist.id,
                code=f"C{i}",
                label=f"Item {i}",
                display_order=i + 1,
            )
        )

    # Operational sets, each bound to the published design version.
    for i in range(plan["subjects"]):
        session.add(
            Subject(
                id=uuid.uuid4(),
                study_id=study.id,
                site_id=uuid.uuid4(),
                study_version_id=version.id,
                subject_number=f"S{i:03d}",
                status=_SUBJECT_STATUSES[i % len(_SUBJECT_STATUSES)],
                created_by=_ACTOR_ID,
                created_at=_FIXED_TS,
            )
        )
    for i in range(plan["visit_instances"]):
        session.add(
            VisitInstance(
                id=uuid.uuid4(),
                subject_id=uuid.uuid4(),
                visit_definition_id=uuid.uuid4(),
                design_version_id=version.id,
                name=f"Visit {i}",
                created_at=_FIXED_TS,
            )
        )
    form_instance_ids: list[uuid.UUID] = []
    for _ in range(plan["form_instances"]):
        fi_id = uuid.uuid4()
        form_instance_ids.append(fi_id)
        session.add(
            FormInstance(
                id=fi_id,
                subject_id=uuid.uuid4(),
                form_definition_id=form.id,
                design_version_id=version.id,
                created_at=_FIXED_TS,
            )
        )
    # A stable form_instance id for form_records / field_values when no form
    # instance was seeded (SQLite does not enforce the FK).
    owner_fi = form_instance_ids[0] if form_instance_ids else uuid.uuid4()
    for i in range(plan["form_records"]):
        session.add(
            FormRecord(
                id=uuid.uuid4(),
                form_instance_id=owner_fi,
                design_version_id=version.id,
                sequence_number=i + 1,
                created_at=_FIXED_TS,
            )
        )
    shapes = plan["field_value_shapes"]
    for i in range(plan["field_values"]):
        raw = _FIELD_VALUE_SHAPES[shapes[i % len(shapes)]]
        session.add(
            FieldValue(
                id=uuid.uuid4(),
                form_instance_id=owner_fi,
                field_definition_id=field.id,
                design_version_id=version.id,
                value=raw,
                is_not_applicable=raw is None,
                created_at=_FIXED_TS,
            )
        )

    await session.commit()
    return version.id


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(plan=_seed_plan())
async def test_migration_preserves_record_count_and_values(plan: dict[str, int]):
    """Reassignment preserves every set's count and value checksum (R11.1/2/5).

    **Validates: Requirements 11.1, 11.2, 11.5**

    For any seeded database, capturing the Phase 0 snapshot, running Phase 4
    reassignment, and verifying yields ``ok=True`` with no failing sets, and the
    post-migration count AND value checksum of every reassigned record set equal
    the pre-migration snapshot exactly.
    """
    # A fresh engine per example keeps Hypothesis examples fully isolated.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            design_version_id = await _seed(session, plan)

            # Phase 0: capture the pre-migration snapshot.
            pre_snapshot = await snapshot_service.capture(session)

            # Phase 4: run the ownership reassignment (logical; no value rewrite).
            await reassignment_service.reassign_all(session, actor_id=_ACTOR_ID)

            # Phases 5-6: verify preservation against the Phase 0 snapshot.
            result = await VerificationService().verify(session, pre_snapshot)

        # Verification passes: no data-loss risk, no non-consumable design.
        assert result.ok is True
        assert result.failing_sets == []
        assert result.failing_published_designs == []
        assert design_version_id in result.published_designs_consumable

        # Directly assert every reassigned set's count AND value checksum are
        # byte-identical to the Phase 0 snapshot. (verify() compares an
        # internally-captured fresh snapshot; this re-captures independently so
        # the count/value-preservation guarantee of R11.5 is asserted explicitly.)
        async with factory() as session:
            post_snapshot = await snapshot_service.capture(session)
        for name in RECORD_SET_MODELS:
            pre = pre_snapshot.get(name)
            post = post_snapshot.get(name)
            assert post is not None
            assert post.count == pre.count, f"count drift in {name}"
            assert post.checksum == pre.checksum, f"value drift in {name}"
    finally:
        await engine.dispose()
