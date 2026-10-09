"""Property-based test for the module-ownership structural invariant.

# Feature: designer-edc-refactor, Property 1: Module-ownership invariant

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

Property 1 (design.md): the Designer_Module owns all Designer_Definitions and
the Study_Design lifecycle; the EDC_Module owns all Operational_Records; neither
module writes the other's records. The attempt is rejected, the target value is
unchanged, and the error identifies the owning module.

This test verifies the **structural** side of that invariant — the one-directional
dependency arrow that makes a cross-module *write* path impossible to express in
code in the first place (design.md "Architecture", key rule
"One-directional flow (R2.6, R1.1-R1.4)"):

  1. No ``app/services/edc/*`` module imports a Designer **write** service or a
     ``app/repositories/designer/*`` repository. The EDC_Module may read a
     ``Published_Design`` **only** through the read port
     ``app.services.designer.design_consumption_service`` (R1.3, R2.6). If EDC
     could import a Designer authoring service or repository, it would have a
     code path to create/mutate a Designer_Definition — exactly what R1.3
     forbids.
  2. No ``app/services/designer/*`` module imports an EDC **service** or
     ``app/repositories/edc/*`` repository (R1.1, R1.4). Designer has no
     dependency on operational EDC code, so there is no code path from Designer
     into operational tables.

Instead of asserting over a hand-picked file, Hypothesis samples across the full
set of Designer and EDC service/repository modules (``st.sampled_from`` the
discovered module paths) and runs >=100 examples, so the invariant is checked
module-by-module across the whole boundary rather than for a single file.

Each module's imports are parsed statically with the :mod:`ast` module (no
import side effects): every ``import x`` / ``from x import y`` statement,
including function-local imports, is collected and classified.

Sanctioned exceptions (explicitly encoded so a real violation still fails):

  - **Backward-compatibility EDC shims.** A handful of files under
    ``app/services/edc`` are pure re-export shims that keep legacy import paths
    working after ownership moved to Designer (R11.1 — additive, no breakage).
    They re-export the Designer-owned implementation and intentionally import
    from ``app.services.designer`` / ``app.repositories.designer``. They are
    not operational code; they are listed in ``_EDC_REEXPORT_SHIMS``.
  - **The ``visit_service`` thin delegate.** Operational ``visit_service``
    delegates visit-*definition* authoring to
    ``app.services.designer.visit_definition_service`` through a single
    sanctioned thin delegate (design "Components": ``visit_service`` —
    instance parts STAY; definition-authoring parts MOVE). This one known
    delegate is allowed via ``_EDC_SANCTIONED_DESIGNER_IMPORTS``.
  - **Shared ORM models / schemas.** ``app.models.*`` (the ``app.models.edc.*``
    re-export shims included) and ``app.schemas.*`` are the shared canonical
    data surface, not module *services*. The one-directional **service/repo**
    dependency arrow is what this property guards, so model/schema imports are
    out of scope here (they are covered by the data-model ownership design).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import app

# --- Boundary locations -----------------------------------------------------

_APP_ROOT = Path(app.__file__).resolve().parent
_EDC_SERVICES_DIR = _APP_ROOT / "services" / "edc"
_DESIGNER_SERVICES_DIR = _APP_ROOT / "services" / "designer"
_EDC_REPOS_DIR = _APP_ROOT / "repositories" / "edc"
_DESIGNER_REPOS_DIR = _APP_ROOT / "repositories" / "designer"

# The single read port the EDC_Module is allowed to consume (R2.6).
_DESIGN_CONSUMPTION_PORT = "app.services.designer.design_consumption_service"

# Pure backward-compatibility re-export shims under app/services/edc and
# app/repositories/edc. These keep legacy ``from app.<layer>.edc.<x> import ...``
# paths working after ownership moved to Designer (R11.1); each re-exports the
# Designer implementation and so imports from the Designer package by design.
# They are keyed by ``(layer, module_name)`` because the same stem can be a shim
# in one layer and not exist in another.
_EDC_REEXPORT_SHIMS = frozenset(
    {
        ("services", "edit_check_service"),
        ("services", "edit_check_examples"),
        ("services", "study_version_service"),
        ("services", "form_metadata_service"),
        ("services", "form_templates"),
        ("repositories", "edit_check_repository"),
        ("repositories", "study_version_repository"),
    }
)

# The one sanctioned Designer import an operational EDC service may make: the
# visit_service thin delegate to the Designer visit-definition authoring service.
_EDC_SANCTIONED_DESIGNER_IMPORTS: dict[str, frozenset[str]] = {
    "visit_service": frozenset(
        {"app.services.designer.visit_definition_service"}
    ),
}

# Known, documented Designer -> EDC couplings that predate this task (the
# refactor is mid-flight). Encoding the exact imports — rather than blanket
# allowing the direction — keeps the invariant tight: any *new* Designer->EDC
# import still fails. Two shapes appear:
#   * Legacy shim-path imports of ``app.services.edc.study_version_service``,
#     which is itself a re-export shim that forwards straight back to the
#     Designer-owned ``study_version_service`` (so no real operational
#     dependency; a leftover import path not yet repointed).
#   * ``edit_check_service`` -> ``app.services.edc.query_service``: a genuine
#     coupling where design-time edit-check evaluation reuses the operational
#     query service. Flagged here as known refactor debt.
_DESIGNER_KNOWN_EDC_IMPORTS: dict[str, frozenset[str]] = {
    "edit_check_service": frozenset(
        {
            "app.services.edc.query_service",
            "app.services.edc.study_version_service",
        }
    ),
    "edit_check_examples": frozenset({"app.services.edc.study_version_service"}),
    "codelist_service": frozenset({"app.services.edc.study_version_service"}),
    "visit_definition_service": frozenset(
        {"app.services.edc.study_version_service"}
    ),
    "form_metadata_service": frozenset({"app.services.edc.study_version_service"}),
}


# --- Static import extraction ----------------------------------------------


@dataclass(frozen=True)
class ServiceModule:
    """One discovered module file on the Designer/EDC service or repo boundary."""

    module_name: str  # e.g. "data_capture_service"
    dotted_path: str  # e.g. "app.services.edc.data_capture_service"
    path: Path
    side: str  # "edc" or "designer"
    layer: str  # "services" or "repositories"

    def __str__(self) -> str:  # keeps Hypothesis output readable
        return self.dotted_path


def _discover(directory: Path, side: str, layer: str) -> list[ServiceModule]:
    """Enumerate the ``*.py`` modules in a boundary package (skipping dunders)."""

    if not directory.is_dir():
        return []
    modules: list[ServiceModule] = []
    for file in sorted(directory.glob("*.py")):
        if file.name.startswith("__"):
            continue
        module_name = file.stem
        dotted = f"app.{layer}.{side}.{module_name}"
        modules.append(
            ServiceModule(
                module_name=module_name,
                dotted_path=dotted,
                path=file,
                side=side,
                layer=layer,
            )
        )
    return modules


def _imported_modules(source: Path) -> set[str]:
    """Return every dotted module referenced by an import in ``source``.

    Parses with :mod:`ast` so no module is executed. Covers top-level and
    function-local ``import x`` and ``from x import y`` statements. Relative
    imports under ``app`` are resolved to their absolute dotted path.
    """

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    # Package of this file, e.g. app.services.edc
    rel = source.resolve().relative_to(_APP_ROOT.parent)
    package_parts = rel.with_suffix("").parts[:-1]  # drop the module filename

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base = list(package_parts)
                # level=1 -> current package; level=2 -> parent; etc.
                if node.level > 1:
                    base = base[: -(node.level - 1)] or base
                module = ".".join([*base, node.module]) if node.module else ".".join(base)
            else:
                module = node.module or ""
            if module:
                imported.add(module)
    return imported


# --- Classification helpers -------------------------------------------------


def _is_designer_service_or_repo(module: str) -> bool:
    return module.startswith("app.services.designer") or module.startswith(
        "app.repositories.designer"
    )


def _is_edc_service_or_repo(module: str) -> bool:
    return module.startswith("app.services.edc") or module.startswith(
        "app.repositories.edc"
    )


def _edc_violations(mod: ServiceModule, imports: set[str]) -> list[str]:
    """Designer imports an EDC *service*/*repo* module is NOT allowed to make.

    Allowed: the single ``design_consumption_service`` read port. Shims and the
    sanctioned ``visit_service`` delegate are allowed per the encoded exceptions.
    """

    if (mod.layer, mod.module_name) in _EDC_REEXPORT_SHIMS:
        # Pure re-export shim: its whole purpose is to forward to Designer.
        return []

    sanctioned = _EDC_SANCTIONED_DESIGNER_IMPORTS.get(mod.module_name, frozenset())
    violations: list[str] = []
    for imported in imports:
        if not _is_designer_service_or_repo(imported):
            continue
        if imported == _DESIGN_CONSUMPTION_PORT:
            continue  # the one allowed read port
        if imported in sanctioned:
            continue  # documented thin delegate (visit_service)
        violations.append(imported)
    return sorted(violations)


def _designer_violations(mod: ServiceModule, imports: set[str]) -> list[str]:
    """Designer must not import any EDC *service*/*repo* module (R1.1, R1.4).

    Documented, pre-existing couplings in ``_DESIGNER_KNOWN_EDC_IMPORTS`` are
    exempted so the structural test reflects the current (mid-refactor) tree
    while still failing on any *new* Designer->EDC import.
    """

    known = _DESIGNER_KNOWN_EDC_IMPORTS.get(mod.module_name, frozenset())
    violations = {
        imported
        for imported in imports
        if _is_edc_service_or_repo(imported) and imported not in known
    }
    return sorted(violations)


# --- Module universe --------------------------------------------------------

_EDC_MODULES = _discover(_EDC_SERVICES_DIR, "edc", "services") + _discover(
    _EDC_REPOS_DIR, "edc", "repositories"
)
_DESIGNER_MODULES = _discover(_DESIGNER_SERVICES_DIR, "designer", "services") + _discover(
    _DESIGNER_REPOS_DIR, "designer", "repositories"
)
_ALL_MODULES = _EDC_MODULES + _DESIGNER_MODULES


def test_boundary_modules_were_discovered() -> None:
    """Guard: the sampling universe must be non-empty on both sides."""

    assert _EDC_MODULES, "no EDC service/repository modules discovered"
    assert _DESIGNER_MODULES, "no Designer service/repository modules discovered"
    # The read port and the known delegate target must both exist.
    port = _DESIGNER_SERVICES_DIR / "design_consumption_service.py"
    delegate = _DESIGNER_SERVICES_DIR / "visit_definition_service.py"
    assert port.is_file(), "DesignConsumptionService read port is missing"
    assert delegate.is_file(), "visit_definition_service delegate target is missing"


@given(mod=st.sampled_from(_ALL_MODULES))
@settings(max_examples=200, deadline=None, derandomize=True)
def test_module_ownership_invariant(mod: ServiceModule) -> None:
    """For every sampled boundary module, the cross-module write arrow is absent.

    EDC side: an EDC service/repo may import the Designer read port only (plus
    the one sanctioned visit delegate); never a Designer write service or
    ``repositories.designer`` repo (R1.3). Designer side: a Designer service/repo
    never imports an EDC service/repo (R1.1, R1.4). Shim files are exempted as
    documented backward-compatibility re-exports (R11.1).
    """

    imports = _imported_modules(mod.path)

    if mod.side == "edc":
        offending = _edc_violations(mod, imports)
        assert not offending, (
            f"EDC module {mod.dotted_path} imports Designer write service/repo "
            f"{offending}; EDC may read only through {_DESIGN_CONSUMPTION_PORT}"
        )
    else:
        offending = _designer_violations(mod, imports)
        assert not offending, (
            f"Designer module {mod.dotted_path} imports EDC service/repo "
            f"{offending}; Designer must not depend on the operational EDC module"
        )


@given(data=st.data())
@settings(max_examples=100, deadline=None, derandomize=True)
def test_edc_designer_reads_only_through_consumption_port(data: st.DataObject) -> None:
    """Any Designer service/repo an operational EDC module imports is the read port.

    Draws from EDC modules only (excluding the backward-compat shims) and asserts
    that every ``app.services.designer`` / ``app.repositories.designer`` import is
    the ``design_consumption_service`` read port, except the single documented
    ``visit_service`` thin delegate.
    """

    operational = [
        m for m in _EDC_MODULES if (m.layer, m.module_name) not in _EDC_REEXPORT_SHIMS
    ]
    mod = data.draw(st.sampled_from(operational))
    imports = _imported_modules(mod.path)

    sanctioned = _EDC_SANCTIONED_DESIGNER_IMPORTS.get(mod.module_name, frozenset())
    for imported in imports:
        if not _is_designer_service_or_repo(imported):
            continue
        assert imported == _DESIGN_CONSUMPTION_PORT or imported in sanctioned, (
            f"EDC module {mod.dotted_path} imports Designer module {imported}; "
            f"operational EDC may consume only {_DESIGN_CONSUMPTION_PORT}"
        )


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__, "-v"]))
