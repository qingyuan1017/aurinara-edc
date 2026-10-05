"""PV Phase 1 persistence and migration additivity checks.

Feature: pv-safety-module, Task 1.2
Validates: Requirements 3.2, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6

These tests mirror the CTMS Phase 1 qualification approach: they load the
additive Alembic revision to assert it is additive and PV-prefixed, and they
build the ORM schema on the portable in-memory engine to assert PV tables use
UUID PKs, UTC timestamps, canonical references, a globally unique case
identifier, queryable indexes, and soft-deletion/retention columns without
duplicating EDC clinical or CTMS operational tables.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base


def _load_revision():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0038_create_pv_phase1.py"
    spec = importlib.util.spec_from_file_location("pv_phase1_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EDC_TABLES = {
    "studies", "sites", "subjects", "study_versions", "visit_instances",
    "form_instances", "field_values", "queries", "file_attachments", "exports",
    "audit_events",
}

_PV_TABLES = {
    "pv_safety_cases",
    "pv_adverse_event_records",
    "pv_case_versions",
    "pv_seriousness_assessments",
}


def test_pv_phase1_revision_is_additive_and_pv_prefixed():
    revision = _load_revision()
    assert revision.revision == "0038"
    assert revision.down_revision == "0037"
    assert set(revision._PV_TABLES) == _PV_TABLES
    assert all(name.startswith("pv_") for name in revision._PV_TABLES)
    # No PV table shadows an EDC clinical or CTMS operational table.
    assert _EDC_TABLES.isdisjoint(revision._PV_TABLES)
    assert all(not name.startswith("ctms_") for name in revision._PV_TABLES)
    # PV depends on canonical identity and the immutable audit trail.
    assert set(revision._REQUIRED_EDC_TABLES) == {
        "users", "studies", "sites", "subjects", "permissions",
    }
    # Safety_Data tables are protected against physical deletion.
    assert set(revision._PROTECTED_SAFETY_TABLES) == _PV_TABLES
    assert {code for code, _ in revision._PV_PERMISSIONS} == {
        "safety_case.enter",
        "safety_case.read",
        "safety_case.lifecycle",
        "safety_assessment.record",
        "safety_audit.read",
    }


def test_pv_model_metadata_conventions_and_no_duplicate_tables():
    import app.models  # noqa: F401 - register all mapped models

    tables = Base.metadata.tables
    assert _PV_TABLES.issubset(tables)
    assert _PV_TABLES.isdisjoint(_EDC_TABLES)
    assert all(not name.startswith("ctms_") for name in _PV_TABLES)

    case = tables["pv_safety_cases"]
    case_columns = set(case.c.keys())
    # UUID PK, canonical scope, and referenced EDC subject identity.
    assert {"study_id", "site_id", "subject_reference"}.issubset(case_columns)
    # Actor/correlation, retention, and soft-deletion columns.
    for column in (
        "created_by", "updated_by", "correlation_id",
        "retention_state", "archived_at", "retention_reason",
        "deleted_at", "deleted_by", "deletion_reason",
    ):
        assert column in case_columns, column
    # UTC-aware timestamps.
    assert case.c.created_at.type.timezone is True
    assert case.c.updated_at.type.timezone is True

    # Globally unique safety case identifier (Req 3.2, 17.4).
    assert any(
        index.unique and [c.name for c in index.columns] == ["case_identifier"]
        for index in case.indexes
    )

    # Queryable indexes for the required dimensions (Req 17.5).
    indexed_columns = {
        tuple(c.name for c in index.columns) for index in case.indexes
    }
    assert ("study_id",) in indexed_columns
    assert ("site_id",) in indexed_columns
    assert ("subject_reference",) in indexed_columns
    assert ("study_id", "lifecycle_state") in indexed_columns
    assert ("created_at",) in indexed_columns

    ae = tables["pv_adverse_event_records"]
    assert "case_id" in set(ae.c.keys())
    version = tables["pv_case_versions"]
    assert {"case_id", "sequence_number", "version_kind", "status"}.issubset(set(version.c.keys()))
    seriousness = tables["pv_seriousness_assessments"]
    assert {"ae_id", "serious", "criteria"}.issubset(set(seriousness.c.keys()))


@pytest.mark.asyncio
async def test_pv_phase1_schema_creates_and_soft_deletion_columns_persist():
    import app.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert _PV_TABLES.issubset(names)

        from app.models.pv import RetentionState, SafetyCase

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            case = SafetyCase(
                case_identifier="CASE-0001",
                study_id=__import__("uuid").uuid4(),
                site_id=__import__("uuid").uuid4(),
                subject_reference=__import__("uuid").uuid4(),
                case_type="Adverse Event",
            )
            session.add(case)
            await session.commit()
            await session.refresh(case)
            # Default retention is active and timestamps are populated (UTC).
            assert case.retention_state == RetentionState.ACTIVE.value
            assert case.created_at is not None
            assert case.deleted_at is None
    finally:
        await engine.dispose()
