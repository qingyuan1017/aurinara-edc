"""Unit tests for the post-migration VerificationService (Migration Phases 5-6).

Validates:
  - R11.5: for every reassigned record set the post-migration count and value
           checksum equal the Phase 0 snapshot.
  - R11.6: any data-loss risk aborts, names the failing record set(s), and leaves
           the pre-migration records unchanged (verification is read-only).
  - R11.3: every pre-migration published design remains consumable through the
           Design_Consumption_Contract.

Tests run against a real in-memory SQLite async session. A "clean" migration is
modeled by capturing the Phase 0 snapshot and verifying against the same,
unchanged database (the refactor never rewrites a value). Count/checksum
mismatches are simulated by tampering the *pre-migration* snapshot so it no
longer matches the fresh snapshot captured from the DB. A non-consumable design
is simulated by injecting a consumption-service stub that raises.
"""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  (register every ORM table for create_all)
from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.services.designer.design_consumption_service import (
    design_consumption_service,
)
from app.services.designer.migration.snapshot_service import snapshot_service
from app.services.designer.migration.verification_service import (
    FailureKind,
    MigrationAbortError,
    VerificationResult,
    VerificationService,
)


@pytest.fixture
async def session_factory():
    """Yield an async_sessionmaker over a fresh in-memory SQLite engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield factory
    await engine.dispose()


async def _seed_published_design(session: AsyncSession) -> dict[str, uuid.UUID]:
    """Seed a Study + a *published* Design_Version with design-time content.

    Returns the study id and the published design_version_id. The content
    mirrors a minimal but complete published design so the consumption contract
    resolves a non-empty Published_Design view.
    """
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Verification Study",
        status=StudyStatus.active,
        created_by=uuid.uuid4(),
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
        form_definition_id=form.id,
        name="Basics",
        display_order=1,
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
    session.add(
        VisitDefinition(
            study_version_id=version.id,
            name="Screening",
            visit_number=1,
            visit_type="scheduled",
            display_order=1,
            is_required=True,
        )
    )
    codelist = Codelist(
        study_version_id=version.id,
        name="Gender",
        code="GENDER",
    )
    session.add(codelist)
    await session.flush()
    session.add_all(
        [
            CodelistItem(
                codelist_id=codelist.id, code="M", label="Male", display_order=1
            ),
            CodelistItem(
                codelist_id=codelist.id, code="F", label="Female", display_order=2
            ),
        ]
    )
    await session.commit()
    return {"study_id": study.id, "design_version_id": version.id}


class _RaisingConsumptionService:
    """Consumption-service stub that raises for one specific version id.

    Delegates every published version to the real service except the one id it
    is told to fail, which raises NotFoundError to model a design that is no
    longer consumable through the Design_Consumption_Contract (R11.3).
    """

    def __init__(self, fail_version_id: uuid.UUID) -> None:
        self._fail_version_id = fail_version_id

    async def get_published_design(self, session, design_version_id):
        if design_version_id == self._fail_version_id:
            raise NotFoundError(
                "Published design version not found",
                details={"design_version_id": str(design_version_id)},
            )
        return await design_consumption_service.get_published_design(
            session, design_version_id
        )


# --- Clean (no-change) migration -------------------------------------------


async def test_clean_migration_verifies_ok(session_factory):
    """A no-change migration verifies OK: counts+checksums match, designs OK."""
    async with session_factory() as seed:
        ids = await _seed_published_design(seed)

    async with session_factory() as session:
        pre_snapshot = await snapshot_service.capture(session)
        service = VerificationService()

        result = await service.verify(session, pre_snapshot)

    assert isinstance(result, VerificationResult)
    assert result.ok is True
    assert result.failing_sets == []
    assert result.failing_published_designs == []
    assert ids["design_version_id"] in result.published_designs_consumable


async def test_clean_migration_verify_or_abort_returns_result(session_factory):
    """verify_or_abort returns the ok result when nothing changed (no raise)."""
    async with session_factory() as seed:
        await _seed_published_design(seed)

    async with session_factory() as session:
        pre_snapshot = await snapshot_service.capture(session)
        service = VerificationService()

        result = await service.verify_or_abort(session, pre_snapshot)

    assert result.ok is True


# --- Count mismatch aborts and names the failing set ------------------------


async def test_count_mismatch_aborts_and_names_failing_set(session_factory):
    """A set whose pre-count differs from the post-count aborts, named (R11.6)."""
    async with session_factory() as seed:
        await _seed_published_design(seed)

    async with session_factory() as session:
        pre_snapshot = await snapshot_service.capture(session)
        # Simulate a data-loss risk: the pre-migration snapshot recorded one
        # MORE codelist_item than the DB now holds (a lost row).
        original = pre_snapshot.get("codelist_items")
        tampered = replace(original, count=original.count + 1)
        pre_snapshot.record_sets["codelist_items"] = tampered

        service = VerificationService()
        result = await service.verify(session, pre_snapshot)

    assert result.ok is False
    assert "codelist_items" in result.failing_set_names
    (failure,) = [
        f for f in result.failing_sets if f.record_set == "codelist_items"
    ]
    assert failure.kind is FailureKind.COUNT_MISMATCH
    assert failure.expected_count == original.count + 1
    assert failure.actual_count == original.count


async def test_count_mismatch_verify_or_abort_raises(session_factory):
    """verify_or_abort raises MigrationAbortError carrying the failing set."""
    async with session_factory() as seed:
        await _seed_published_design(seed)

    async with session_factory() as session:
        pre_snapshot = await snapshot_service.capture(session)
        original = pre_snapshot.get("codelist_items")
        pre_snapshot.record_sets["codelist_items"] = replace(
            original, count=original.count + 1
        )

        service = VerificationService()
        with pytest.raises(MigrationAbortError) as exc_info:
            await service.verify_or_abort(session, pre_snapshot)

    result = exc_info.value.result
    assert result.ok is False
    assert "codelist_items" in result.failing_set_names


# --- Value (checksum) mismatch aborts and names the failing set -------------


async def test_checksum_mismatch_aborts_and_names_failing_set(session_factory):
    """A set whose stored values changed (checksum differs) aborts, named."""
    async with session_factory() as seed:
        await _seed_published_design(seed)

    async with session_factory() as session:
        pre_snapshot = await snapshot_service.capture(session)
        # Simulate a value change: same count, different checksum. The refactor
        # must never rewrite a stored value, so this is a data-loss risk (R11.5).
        original = pre_snapshot.get("form_definitions")
        tampered_checksum = "f" * 64 if original.checksum != "f" * 64 else "e" * 64
        pre_snapshot.record_sets["form_definitions"] = replace(
            original, checksum=tampered_checksum
        )

        service = VerificationService()
        result = await service.verify(session, pre_snapshot)

    assert result.ok is False
    assert "form_definitions" in result.failing_set_names
    (failure,) = [
        f for f in result.failing_sets if f.record_set == "form_definitions"
    ]
    assert failure.kind is FailureKind.CHECKSUM_MISMATCH
    assert failure.expected_count == failure.actual_count
    assert failure.expected_checksum != failure.actual_checksum


# --- Non-consumable published design aborts ---------------------------------


async def test_non_consumable_published_design_aborts(session_factory):
    """A published design that cannot be consumed aborts verification (R11.3)."""
    async with session_factory() as seed:
        ids = await _seed_published_design(seed)
    fail_id = ids["design_version_id"]

    async with session_factory() as session:
        pre_snapshot = await snapshot_service.capture(session)
        service = VerificationService(
            consumption_service=_RaisingConsumptionService(fail_id)
        )
        result = await service.verify(session, pre_snapshot)

    assert result.ok is False
    # The counts/checksums are untouched — only the consumability check failed.
    assert result.failing_sets == []
    assert fail_id in [
        f.design_version_id for f in result.failing_published_designs
    ]
    assert fail_id not in result.published_designs_consumable


async def test_verification_is_read_only(session_factory):
    """Verification performs no writes: DB rows are unchanged after verify (R11.6)."""
    async with session_factory() as seed:
        await _seed_published_design(seed)

    async with session_factory() as session:
        before = (
            await session.execute(select(StudyVersion.id))
        ).scalars().all()
        pre_snapshot = await snapshot_service.capture(session)

        service = VerificationService()
        await service.verify(session, pre_snapshot)

        after = (
            await session.execute(select(StudyVersion.id))
        ).scalars().all()

    assert set(before) == set(after)
