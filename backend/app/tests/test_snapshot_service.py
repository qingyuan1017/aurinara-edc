"""Unit tests for the pre-migration SnapshotService (Migration Phase 0).

Validates Requirement 11.5: the Phase 0 snapshot records, per record set, a row
count and an order-independent value checksum that is stable across repeated
captures and sensitive to any change in any stored value.

Tests exercise the service against a real in-memory SQLite async session (FK
constraints are not enforced by SQLite by default, so individual record sets can
be seeded in isolation without materializing the full relational tree).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.edc.form_data import FieldValue
from app.models.edc.form_metadata import Codelist, CodelistItem
from app.models.edc.study import Study, StudyStatus
from app.services.designer.migration.snapshot_service import (
    RECORD_SET_MODELS,
    SNAPSHOT_VERSION,
    SnapshotService,
    snapshot_service,
)


@pytest.fixture
async def db_session() -> AsyncSession:
    """Yield a fresh in-memory SQLite async session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# --- Seed helpers -----------------------------------------------------------
#
# Each helper returns the list of rows it added (in insertion order) so tests
# can re-seed the same logical rows in a different order on a second engine.


def _make_codelist(study_version_id: uuid.UUID, code: str, name: str) -> Codelist:
    return Codelist(
        id=uuid.uuid4(),
        study_version_id=study_version_id,
        name=name,
        code=code,
    )


def _make_codelist_item(
    item_id: uuid.UUID,
    codelist_id: uuid.UUID,
    code: str,
    label: str,
    display_order: int,
    normal_low: Decimal | None = None,
    normal_high: Decimal | None = None,
) -> CodelistItem:
    return CodelistItem(
        id=item_id,
        codelist_id=codelist_id,
        code=code,
        label=label,
        display_order=display_order,
        normal_low=normal_low,
        normal_high=normal_high,
    )


def _make_study(study_id: uuid.UUID, study_code: str) -> Study:
    return Study(
        id=study_id,
        study_code=study_code,
        protocol_number="PROTO-1",
        title=f"Study {study_code}",
        sponsor="ACME",
        phase="Phase II",
        status=StudyStatus.active,
        created_by=uuid.uuid4(),
    )


# Fixed timestamp so a given logical row hashes identically regardless of when
# it is flushed. FieldValue.created_at defaults to datetime.now(UTC) at flush
# time, which otherwise makes "the same" row differ between two insertion runs.
_FIXED_CREATED_AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

# Fixed bound design version id for operational field_values rows.
# ``FieldValue.design_version_id`` is NOT NULL (migrations 0048/0050 enforce the
# binding to a published design version — R2.7/R7.3/R11.2), so every seeded row
# must carry one. A fixed value keeps a given logical row's checksum identical
# across repeated/reordered insertion runs.
_FIXED_DESIGN_VERSION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _make_field_value(
    value_id: uuid.UUID,
    form_instance_id: uuid.UUID,
    field_definition_id: uuid.UUID,
    value: str | None,
    is_not_applicable: bool = False,
    design_version_id: uuid.UUID = _FIXED_DESIGN_VERSION_ID,
) -> FieldValue:
    return FieldValue(
        id=value_id,
        form_instance_id=form_instance_id,
        field_definition_id=field_definition_id,
        design_version_id=design_version_id,
        value=value,
        is_not_applicable=is_not_applicable,
        created_at=_FIXED_CREATED_AT,
    )


async def _seed_codelist_items(session: AsyncSession) -> list[CodelistItem]:
    """Seed one codelist with several items (fixed IDs for determinism)."""
    sv_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    cl_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    codelist = _make_codelist(sv_id, code="SEX", name="Sex")
    codelist.id = cl_id
    session.add(codelist)
    items = [
        _make_codelist_item(
            uuid.UUID("00000000-0000-0000-0000-00000000000a"),
            cl_id,
            "M",
            "Male",
            1,
        ),
        _make_codelist_item(
            uuid.UUID("00000000-0000-0000-0000-00000000000b"),
            cl_id,
            "F",
            "Female",
            2,
            normal_low=Decimal("1.0"),
            normal_high=Decimal("9.5"),
        ),
        _make_codelist_item(
            uuid.UUID("00000000-0000-0000-0000-00000000000c"),
            cl_id,
            "U",
            "Unknown",
            3,
        ),
    ]
    session.add_all(items)
    await session.flush()
    return items


async def _seed_field_values(session: AsyncSession) -> list[FieldValue]:
    """Seed operational field_values covering several value shapes."""
    fi_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    fd_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    values = [
        _make_field_value(
            uuid.UUID("00000000-0000-0000-0000-0000000000a1"), fi_id, fd_id, "72"
        ),
        _make_field_value(
            uuid.UUID("00000000-0000-0000-0000-0000000000a2"), fi_id, fd_id, "mild"
        ),
        _make_field_value(
            uuid.UUID("00000000-0000-0000-0000-0000000000a3"),
            fi_id,
            fd_id,
            None,
            is_not_applicable=True,
        ),
    ]
    session.add_all(values)
    await session.flush()
    return values


# --- Count correctness ------------------------------------------------------


async def test_counts_match_seeded_rows(db_session: AsyncSession):
    """count equals the number of seeded rows for each record set."""
    items = await _seed_codelist_items(db_session)
    field_values = await _seed_field_values(db_session)

    snapshot = await snapshot_service.capture(db_session)

    assert snapshot.get("codelists").count == 1
    assert snapshot.get("codelist_items").count == len(items)
    assert snapshot.get("field_values").count == len(field_values)
    # Record sets with no seeded rows are reported as empty.
    assert snapshot.get("studies").count == 0


async def test_empty_record_set_has_zero_count_and_zero_checksum(db_session: AsyncSession):
    """An empty record set reports count 0 and the canonical all-zero checksum."""
    snapshot = await snapshot_service.capture(db_session)

    for name in RECORD_SET_MODELS:
        rs = snapshot.get(name)
        assert rs is not None
        assert rs.count == 0
        assert rs.checksum == "0" * 64


async def test_snapshot_covers_every_declared_record_set(db_session: AsyncSession):
    """capture() produces exactly one entry per declared record set."""
    snapshot = await snapshot_service.capture(db_session)

    assert snapshot.version == SNAPSHOT_VERSION
    assert set(snapshot.record_sets) == set(RECORD_SET_MODELS)


# --- Checksum stability -----------------------------------------------------


async def test_checksum_stable_across_repeated_captures(db_session: AsyncSession):
    """Capturing the same unchanged data twice yields identical checksums."""
    await _seed_codelist_items(db_session)
    await _seed_field_values(db_session)

    first = await snapshot_service.capture(db_session)
    second = await snapshot_service.capture(db_session)

    for name in RECORD_SET_MODELS:
        assert first.get(name).count == second.get(name).count
        assert first.get(name).checksum == second.get(name).checksum


async def test_nonempty_checksum_is_64_char_hex(db_session: AsyncSession):
    """A populated record set produces a 64-char lowercase hex checksum."""
    await _seed_codelist_items(db_session)

    snapshot = await snapshot_service.capture(db_session)
    checksum = snapshot.get("codelist_items").checksum

    assert len(checksum) == 64
    assert checksum != "0" * 64
    assert all(c in "0123456789abcdef" for c in checksum)


# --- Order independence ------------------------------------------------------


async def _capture_set_in_isolated_engine(seed_rows: list, record_set: str) -> str:
    """Create a fresh engine, add seed_rows in the given order, snapshot one set."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            for row in seed_rows:
                session.add(row)
            await session.flush()
            snapshot = await snapshot_service.capture(session)
            return snapshot.get(record_set).checksum
    finally:
        await engine.dispose()


async def test_checksum_order_independent_for_field_values():
    """Same rows inserted in different orders produce the same set checksum."""
    fi_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    fd_id = uuid.UUID("44444444-4444-4444-4444-444444444444")

    def rows() -> list[FieldValue]:
        return [
            _make_field_value(
                uuid.UUID("00000000-0000-0000-0000-0000000000b1"), fi_id, fd_id, "alpha"
            ),
            _make_field_value(
                uuid.UUID("00000000-0000-0000-0000-0000000000b2"), fi_id, fd_id, "beta"
            ),
            _make_field_value(
                uuid.UUID("00000000-0000-0000-0000-0000000000b3"), fi_id, fd_id, "gamma"
            ),
        ]

    forward = rows()
    reversed_rows = list(reversed(rows()))

    checksum_forward = await _capture_set_in_isolated_engine(forward, "field_values")
    checksum_reversed = await _capture_set_in_isolated_engine(reversed_rows, "field_values")

    assert checksum_forward == checksum_reversed
    assert checksum_forward != "0" * 64


async def test_checksum_order_independent_for_codelist_items():
    """Codelist items inserted in a shuffled order yield the same checksum."""
    cl_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

    def rows() -> list[CodelistItem]:
        return [
            _make_codelist_item(
                uuid.UUID("00000000-0000-0000-0000-0000000000c1"), cl_id, "A", "A label", 1
            ),
            _make_codelist_item(
                uuid.UUID("00000000-0000-0000-0000-0000000000c2"), cl_id, "B", "B label", 2
            ),
            _make_codelist_item(
                uuid.UUID("00000000-0000-0000-0000-0000000000c3"), cl_id, "C", "C label", 3
            ),
        ]

    original = rows()
    shuffled = rows()
    shuffled = [shuffled[1], shuffled[2], shuffled[0]]

    checksum_original = await _capture_set_in_isolated_engine(original, "codelist_items")
    checksum_shuffled = await _capture_set_in_isolated_engine(shuffled, "codelist_items")

    assert checksum_original == checksum_shuffled
    assert checksum_original != "0" * 64


# --- Value sensitivity ------------------------------------------------------


async def test_checksum_changes_when_a_value_changes():
    """Changing one field of one row changes the set-level checksum."""
    fi_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    fd_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    row_id = uuid.UUID("00000000-0000-0000-0000-0000000000d1")

    baseline = [_make_field_value(row_id, fi_id, fd_id, "72")]
    mutated = [_make_field_value(row_id, fi_id, fd_id, "73")]

    checksum_baseline = await _capture_set_in_isolated_engine(baseline, "field_values")
    checksum_mutated = await _capture_set_in_isolated_engine(mutated, "field_values")

    assert checksum_baseline != checksum_mutated


async def test_checksum_sensitive_to_null_vs_empty_string():
    """A NULL value and an empty-string value hash differently."""
    fi_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    fd_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    row_id = uuid.UUID("00000000-0000-0000-0000-0000000000d2")

    null_row = [_make_field_value(row_id, fi_id, fd_id, None)]
    empty_row = [_make_field_value(row_id, fi_id, fd_id, "")]

    checksum_null = await _capture_set_in_isolated_engine(null_row, "field_values")
    checksum_empty = await _capture_set_in_isolated_engine(empty_row, "field_values")

    assert checksum_null != checksum_empty


async def test_checksum_sensitive_to_decimal_reference_range():
    """Changing a Decimal reference-range bound changes the checksum."""
    cl_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    item_id = uuid.UUID("00000000-0000-0000-0000-0000000000d3")

    baseline = [
        _make_codelist_item(
            item_id, cl_id, "X", "X label", 1,
            normal_low=Decimal("1.0"), normal_high=Decimal("9.5"),
        )
    ]
    mutated = [
        _make_codelist_item(
            item_id, cl_id, "X", "X label", 1,
            normal_low=Decimal("1.0"), normal_high=Decimal("9.6"),
        )
    ]

    checksum_baseline = await _capture_set_in_isolated_engine(baseline, "codelist_items")
    checksum_mutated = await _capture_set_in_isolated_engine(mutated, "codelist_items")

    assert checksum_baseline != checksum_mutated


async def test_adding_a_row_changes_count_and_checksum():
    """Adding a row increases count and alters the set checksum."""
    cl_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    one_row = [
        _make_codelist_item(
            uuid.UUID("00000000-0000-0000-0000-0000000000e1"), cl_id, "A", "A", 1
        )
    ]
    two_rows = [
        *one_row,
        _make_codelist_item(
            uuid.UUID("00000000-0000-0000-0000-0000000000e2"), cl_id, "B", "B", 2
        ),
    ]

    checksum_one = await _capture_set_in_isolated_engine(one_row, "codelist_items")
    checksum_two = await _capture_set_in_isolated_engine(two_rows, "codelist_items")

    assert checksum_one != checksum_two


# --- Service construction ---------------------------------------------------


async def test_single_record_set_snapshot(db_session: AsyncSession):
    """snapshot_record_set snapshots one set with the correct table name."""
    items = await _seed_codelist_items(db_session)
    service = SnapshotService()

    rs = await service.snapshot_record_set(db_session, "codelist_items", CodelistItem)

    assert rs.name == "codelist_items"
    assert rs.table == CodelistItem.__tablename__
    assert rs.count == len(items)
    assert rs.checksum != "0" * 64
