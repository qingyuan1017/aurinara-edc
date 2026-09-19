"""Focused tests for CTMS persistence conventions and phase-1 migration metadata."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect

from app.core.database import Base
from app.models.ctms.common import CTMSRecordMixin, RetentionState


class ExampleCTMSRecord(CTMSRecordMixin, Base):
    """Small declarative model used to verify the reusable mixin contract."""

    __tablename__ = "test_ctms_records"


def _load_phase1_revision():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0024_create_ctms_phase1.py"
    spec = importlib.util.spec_from_file_location("ctms_phase1_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ctms_record_mixin_contains_shared_persistence_contract() -> None:
    columns = inspect(ExampleCTMSRecord).columns

    expected = {
        "id",
        "created_by",
        "updated_by",
        "correlation_id",
        "idempotency_key",
        "created_at",
        "updated_at",
        "retention_state",
        "archived_at",
        "retention_reason",
        "deleted_at",
        "deleted_by",
        "deletion_reason",
    }
    assert expected.issubset(columns.keys())
    assert columns["id"].primary_key
    assert columns["created_at"].type.timezone
    assert columns["updated_at"].type.timezone
    assert columns["archived_at"].type.timezone
    assert columns["deleted_at"].type.timezone
    assert RetentionState.ACTIVE.value == "active"


def test_phase1_revision_is_additive_and_references_canonical_edc_tables() -> None:
    revision = _load_phase1_revision()

    assert revision.revision == "0024"
    assert revision.down_revision == "0023"
    assert all(table.startswith("ctms_") for table in revision._CTMS_TABLES)
    assert {"users", "studies", "sites", "subjects"}.issubset(
        revision._REQUIRED_EDC_TABLES
    )
    forbidden_clinical_tables = {
        "study_versions",
        "visit_instances",
        "form_instances",
        "field_values",
        "queries",
        "exports",
    }
    assert forbidden_clinical_tables.isdisjoint(revision._CTMS_TABLES)


def test_ctms_record_defaults_are_constructible_without_clinical_payload() -> None:
    record = ExampleCTMSRecord(
        created_by=uuid4(),
        correlation_id=uuid4().hex,
        idempotency_key="operation-1",
    )

    assert ExampleCTMSRecord.__table__.c.retention_state.default.arg == RetentionState.ACTIVE
    assert record.deleted_at is None
    assert record.deletion_reason is None
