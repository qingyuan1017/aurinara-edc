"""Additive PV authorization permission-seed migration (0039) checks.

Feature: pv-safety-module, Task 1.4
Validates: Requirements 2.1, 2.6, 18.4

Confirms revision 0039 is additive on top of the PV Phase 1 revision (0038),
seeds only the additional PV permission codes, and remains disjoint from the
Phase 1 base seeds so no permission is duplicated.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.core.permissions import PV_PERMISSION_CODES


def _load(name: str, filename: str):
    path = Path(__file__).parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pv_permission_seed_migration_is_additive():
    rev = _load("pv_perm_seed", "0039_seed_pv_authorization_permissions.py")
    assert rev.revision == "0039"
    assert rev.down_revision == "0038"


def test_seeded_codes_are_pv_and_extend_phase1():
    base = _load("pv_phase1", "0038_create_pv_phase1.py")
    additive = _load("pv_perm_seed", "0039_seed_pv_authorization_permissions.py")

    base_codes = {code for code, _ in base._PV_PERMISSIONS}
    additive_codes = {code for code, _ in additive._PV_PERMISSIONS}

    # Additive migration seeds the remaining PV codes without re-seeding Phase 1.
    assert base_codes.isdisjoint(additive_codes)
    # Together they cover the full PV permission namespace.
    assert base_codes | additive_codes == set(PV_PERMISSION_CODES)


def test_additive_codes_match_expected():
    additive = _load("pv_perm_seed", "0039_seed_pv_authorization_permissions.py")
    assert {code for code, _ in additive._PV_PERMISSIONS} == {
        "safety_coding.assign",
        "safety_narrative.write",
        "safety_report.manage",
        "safety_reconciliation.run",
        "safety_export.create",
    }
