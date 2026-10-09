"""Edge-case + example tests for the designer CodelistService.

Feature: designer-edc-refactor, Task 6.3

Validates Requirements:
  - 6.1: A codelist name is 1-100 chars and carries 1-1000 items; the service
         persists the codelist and its items. Exercised here at the item-count
         bounds (1 and 1000 accepted; 0 and 1001 rejected).
  - 6.2: A duplicate codelist name within the Draft_Design is rejected without
         persisting, and the error identifies the duplicate name; the same name
         is allowed in a different Design_Version.
  - 6.3: Publication is rejected when a field definition references a codelist
         absent from the version; the error identifies the missing reference.

Tests run against a real in-memory SQLite async session (the fixture pattern in
``test_subject_phase_service.py`` / ``test_snapshot_service.py``).
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ValidationError
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.schemas.edc.form_metadata import CodelistCreate, CodelistItemCreate
from app.services.designer.codelist_service import CodelistService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def service() -> CodelistService:
    return CodelistService()


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version to own codelists."""
    study = Study(
        study_code=f"STUDY-{uuid4().hex[:8]}",
        title="Codelist Study",
        status=StudyStatus.draft,
        created_by=uuid4(),
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


def _items(count: int) -> list[CodelistItemCreate]:
    """Build ``count`` distinct codelist items."""
    return [
        CodelistItemCreate(code=f"C{i}", label=f"Label {i}", display_order=i)
        for i in range(1, count + 1)
    ]


def _payload(name: str = "Sex", code: str = "SEX", item_count: int = 1) -> CodelistCreate:
    return CodelistCreate(name=name, code=code, items=_items(item_count))


# ---------------------------------------------------------------------------
# Item-count bounds (Requirement 6.1)
# ---------------------------------------------------------------------------


class TestItemCountBounds:
    """Codelist item count accepted at 1 and 1000, rejected at 0 and 1001."""

    @pytest.mark.parametrize("count", [1, 1000])
    async def test_accepts_item_count_at_bounds(self, service, db_session, count):
        """1 and 1000 items are accepted and all items persist (R6.1)."""
        version = await _make_draft_version(db_session)

        codelist = await service.create_codelist(
            db_session,
            version=version,
            data=_payload(item_count=count),
            actor_id=uuid4(),
        )

        assert len(codelist.items) == count
        persisted = (
            await db_session.execute(
                select(func.count())
                .select_from(CodelistItem)
                .where(CodelistItem.codelist_id == codelist.id)
            )
        ).scalar_one()
        assert persisted == count

    @pytest.mark.parametrize("count", [0, 1001])
    async def test_rejects_item_count_out_of_bounds(self, service, db_session, count):
        """0 and 1001 items are rejected and nothing is persisted (R6.1)."""
        version = await _make_draft_version(db_session)

        with pytest.raises(ValidationError) as exc_info:
            await service.create_codelist(
                db_session,
                version=version,
                data=_payload(item_count=count),
                actor_id=uuid4(),
            )
        assert exc_info.value.details["item_count"] == count

        remaining = (
            await db_session.execute(
                select(func.count())
                .select_from(Codelist)
                .where(Codelist.study_version_id == version.id)
            )
        ).scalar_one()
        assert remaining == 0


# ---------------------------------------------------------------------------
# Name bounds (Requirement 6.1)
# ---------------------------------------------------------------------------


class TestNameBounds:
    """Codelist name accepted at 1 and 100 chars, rejected at 0 and 101."""

    @pytest.mark.parametrize("length", [1, 100])
    async def test_accepts_name_at_bounds(self, service, db_session, length):
        """Names of 1 and 100 chars are accepted (R6.1)."""
        version = await _make_draft_version(db_session)

        codelist = await service.create_codelist(
            db_session,
            version=version,
            data=_payload(name="x" * length),
            actor_id=uuid4(),
        )
        assert codelist.name == "x" * length

    async def test_rejects_name_over_max(self, service, db_session):
        """A 101-char name (past the service's 100 cap) is rejected (R6.1)."""
        version = await _make_draft_version(db_session)

        with pytest.raises(ValidationError):
            await service.create_codelist(
                db_session,
                version=version,
                data=_payload(name="x" * 101),
                actor_id=uuid4(),
            )

    @pytest.mark.parametrize("name", ["", "   "])
    async def test_rejects_blank_name(self, service, db_session, name):
        """A blank name (empty or whitespace-only) is rejected (R6.1).

        ``model_construct`` bypasses the schema's own ``min_length`` so the
        service's own 1-100 guard is exercised directly.
        """
        version = await _make_draft_version(db_session)
        data = CodelistCreate.model_construct(name=name, code="SEX", items=_items(1))

        with pytest.raises(ValidationError):
            await service.create_codelist(
                db_session,
                version=version,
                data=data,
                actor_id=uuid4(),
            )


# ---------------------------------------------------------------------------
# Duplicate-name collisions (Requirement 6.2)
# ---------------------------------------------------------------------------


class TestDuplicateName:
    """Name uniqueness is scoped to a single Draft_Design (R6.2)."""

    async def test_rejects_duplicate_name_identifying_duplicate(
        self, service, db_session
    ):
        """A duplicate name is rejected, the error names it, nothing persists."""
        version = await _make_draft_version(db_session)

        await service.create_codelist(
            db_session,
            version=version,
            data=_payload(name="Sex", code="SEX"),
            actor_id=uuid4(),
        )

        with pytest.raises(ConflictError) as exc_info:
            await service.create_codelist(
                db_session,
                version=version,
                data=_payload(name="Sex", code="SEX2"),
                actor_id=uuid4(),
            )
        assert exc_info.value.details["duplicate_name"] == "Sex"

        count = (
            await db_session.execute(
                select(func.count())
                .select_from(Codelist)
                .where(Codelist.study_version_id == version.id)
            )
        ).scalar_one()
        assert count == 1

    async def test_duplicate_check_is_case_insensitive(self, service, db_session):
        """Names differing only in case collide within one Design_Version."""
        version = await _make_draft_version(db_session)

        await service.create_codelist(
            db_session,
            version=version,
            data=_payload(name="Severity", code="SEV"),
            actor_id=uuid4(),
        )

        with pytest.raises(ConflictError):
            await service.create_codelist(
                db_session,
                version=version,
                data=_payload(name="severity", code="SEV2"),
                actor_id=uuid4(),
            )

    async def test_same_name_allowed_in_different_version(self, service, db_session):
        """The same name is allowed in a different Design_Version (R6.2)."""
        version_a = await _make_draft_version(db_session)
        version_b = await _make_draft_version(db_session)

        codelist_a = await service.create_codelist(
            db_session,
            version=version_a,
            data=_payload(name="Sex", code="SEX"),
            actor_id=uuid4(),
        )
        codelist_b = await service.create_codelist(
            db_session,
            version=version_b,
            data=_payload(name="Sex", code="SEX"),
            actor_id=uuid4(),
        )

        assert codelist_a.study_version_id == version_a.id
        assert codelist_b.study_version_id == version_b.id


# ---------------------------------------------------------------------------
# Missing codelist reference on publish (Requirement 6.3)
# ---------------------------------------------------------------------------


async def _make_field_referencing(
    session: AsyncSession, version: StudyVersion, codelist_id
) -> FieldDefinition:
    """Create a form/section/field chain in ``version`` referencing a codelist."""
    form = FormDefinition(
        study_version_id=version.id,
        name="Demographics",
        form_code="DM",
        display_order=1,
    )
    session.add(form)
    await session.flush()

    section = FormSection(
        form_definition_id=form.id,
        name="Main",
        display_order=1,
    )
    session.add(section)
    await session.flush()

    field = FieldDefinition(
        form_section_id=section.id,
        label="Sex",
        variable_name="SEX",
        control_type="dropdown",
        data_type="string",
        codelist_id=codelist_id,
        display_order=1,
    )
    session.add(field)
    await session.flush()
    return field


class TestValidateCodelistReferences:
    """Publication validation of field -> codelist references (R6.3)."""

    async def test_rejects_missing_reference_identifying_it(
        self, service, db_session
    ):
        """A field referencing an absent codelist blocks publication (R6.3)."""
        version = await _make_draft_version(db_session)
        missing_codelist_id = uuid4()
        field = await _make_field_referencing(
            db_session, version, missing_codelist_id
        )

        with pytest.raises(ValidationError) as exc_info:
            await service.validate_codelist_references(db_session, version.id)

        missing = exc_info.value.details["missing_codelist_references"]
        assert len(missing) == 1
        assert missing[0]["field_definition_id"] == str(field.id)
        assert missing[0]["missing_codelist_id"] == str(missing_codelist_id)

    async def test_accepts_present_reference(self, service, db_session):
        """A field referencing a codelist present in the version is valid (R6.3)."""
        version = await _make_draft_version(db_session)
        codelist = await service.create_codelist(
            db_session,
            version=version,
            data=_payload(name="Sex", code="SEX"),
            actor_id=uuid4(),
        )
        await _make_field_referencing(db_session, version, codelist.id)

        # Does not raise.
        await service.validate_codelist_references(db_session, version.id)

    async def test_accepts_no_codelist_references(self, service, db_session):
        """A version whose fields reference no codelist validates cleanly (R6.3)."""
        version = await _make_draft_version(db_session)
        await _make_field_referencing(db_session, version, None)

        await service.validate_codelist_references(db_session, version.id)
