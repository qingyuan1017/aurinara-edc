"""Router-mounting integration test (task 20.1).

Builds the FastAPI app via ``create_app()`` and inspects the mounted routes
through the generated OpenAPI schema to assert the Designer / EDC refactor
mounting contract holds end-to-end:

- The Designer aggregate mounts under ``/api/v1/designer`` and serves the
  design-authoring surfaces (study versions, forms/fields, edit-check testing,
  codelists, subject phases, schedule of assessment, visits, arms, CRF access,
  raw-data variables, coding settings). Cycles are authored as visits of
  ``visit_type == 'cycle'`` through the visits surface (no separate cycle route).
- The slimmed EDC aggregate preserves its operational paths with NO added
  prefix (``/api/v1/studies`` list, ``/api/v1/subjects``, ``/api/v1/visits``,
  ``/api/v1/queries``, ``/api/v1/studies/{study_id}/dashboard``), and
  design-authoring is NO LONGER served on the no-prefix EDC surface.
- CTMS stays under ``/api/v1/ctms`` and PV under ``/api/v1/pv`` (unchanged).

Validates: Requirements 1.1, 11.4
"""

from __future__ import annotations

import pytest

from app.main import create_app

API_V1 = "/api/v1"


@pytest.fixture(scope="module")
def paths() -> dict[str, dict]:
    """The OpenAPI ``paths`` map for a freshly built application."""
    app = create_app()
    return app.openapi()["paths"]


def _methods(paths: dict[str, dict], path: str) -> set[str]:
    """Return the lower-cased HTTP methods declared for ``path`` (empty if none)."""
    return {method.lower() for method in paths.get(path, {})}


# ---------------------------------------------------------------------------
# Designer aggregate — mounted under /api/v1/designer (Requirement 1.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method"),
    [
        # Study-version lifecycle authoring
        (f"{API_V1}/designer/studies/{{study_id}}/versions", "post"),
        (f"{API_V1}/designer/studies/{{study_id}}/amend", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/publish", "post"),
        # Form / field metadata authoring
        (f"{API_V1}/designer/studies/{{study_id}}/forms", "post"),
        (f"{API_V1}/designer/forms/{{form_id}}/fields", "post"),
        # Edit-check authoring and design-time testing
        (f"{API_V1}/designer/edit-checks/{{edit_check_id}}/test", "post"),
        # Additional designer definition surfaces
        (f"{API_V1}/designer/studies/{{study_id}}/codelists", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/subject-phases", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/schedule-of-assessment", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/visits", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/arms", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/arms", "get"),
        # Form / visit dependency authoring
        (f"{API_V1}/designer/forms/{{form_id}}/dependencies", "post"),
        (f"{API_V1}/designer/forms/{{form_id}}/dependencies", "get"),
        (f"{API_V1}/designer/visits/{{visit_id}}/dependencies", "post"),
        (f"{API_V1}/designer/visits/{{visit_id}}/dependencies", "get"),
        (f"{API_V1}/designer/versions/{{version_id}}/crf-access", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/raw-data-variables", "post"),
        (f"{API_V1}/designer/versions/{{version_id}}/coding-settings", "post"),
    ],
)
def test_designer_paths_mounted_under_designer_prefix(
    paths: dict[str, dict], path: str, method: str
) -> None:
    """Design-authoring surfaces are mounted under ``/api/v1/designer/...``."""
    assert path in paths, f"expected designer path {path!r} to be mounted"
    assert method in _methods(paths, path), (
        f"expected {method.upper()} on {path!r}, got {_methods(paths, path)}"
    )


def test_every_designer_path_carries_the_designer_prefix(paths: dict[str, dict]) -> None:
    """No designer-tagged operation leaks outside the ``/api/v1/designer`` prefix."""
    designer_paths = [
        path
        for path, operations in paths.items()
        for op in operations.values()
        if any(tag.startswith("designer-") for tag in op.get("tags", []))
    ]
    assert designer_paths, "expected at least one designer-tagged route"
    for path in designer_paths:
        assert path.startswith(f"{API_V1}/designer/"), (
            f"designer route {path!r} is not under the /api/v1/designer prefix"
        )


# ---------------------------------------------------------------------------
# Slimmed EDC aggregate — operational paths preserved with NO added prefix
# (Requirement 11.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (f"{API_V1}/studies", "get"),  # operational study list
        (f"{API_V1}/subjects/{{subject_id}}", "get"),
        (f"{API_V1}/studies/{{study_id}}/subjects", "get"),
        (f"{API_V1}/visits/{{visit_id}}", "get"),
        (f"{API_V1}/subjects/{{subject_id}}/visits", "get"),
        (f"{API_V1}/queries/{{query_id}}", "get"),
        (f"{API_V1}/studies/{{study_id}}/queries", "get"),
        (f"{API_V1}/studies/{{study_id}}/dashboard", "get"),
    ],
)
def test_edc_operational_paths_preserved_without_prefix(
    paths: dict[str, dict], path: str, method: str
) -> None:
    """Operational EDC paths keep their exact no-prefix location."""
    assert path in paths, f"expected operational EDC path {path!r} to be mounted"
    assert method in _methods(paths, path), (
        f"expected {method.upper()} on {path!r}, got {_methods(paths, path)}"
    )


def test_edc_surface_still_lists_study_versions(paths: dict[str, dict]) -> None:
    """Operational study-info reads (version listing) stay on the EDC surface."""
    path = f"{API_V1}/studies/{{study_id}}/versions"
    assert "get" in _methods(paths, path), (
        "operational study-version listing should remain on the EDC surface"
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        # Study-version *authoring* moved to /designer — must not be on no-prefix EDC
        (f"{API_V1}/studies/{{study_id}}/versions", "post"),
        (f"{API_V1}/studies/{{study_id}}/amend", "post"),
        (f"{API_V1}/versions/{{version_id}}/publish", "post"),
        # Form/field definition authoring moved to /designer
        (f"{API_V1}/forms/{{form_id}}/fields", "post"),
        (f"{API_V1}/studies/{{study_id}}/forms", "post"),
        (f"{API_V1}/forms/{{form_id}}", "get"),
        (f"{API_V1}/fields/{{field_id}}", "patch"),
    ],
)
def test_design_authoring_removed_from_edc_surface(
    paths: dict[str, dict], path: str, method: str
) -> None:
    """Design-authoring is no longer served on the no-prefix EDC surface."""
    assert method not in _methods(paths, path), (
        f"{method.upper()} {path!r} should have moved to /api/v1/designer, "
        "not remain on the no-prefix EDC surface"
    )


# ---------------------------------------------------------------------------
# CTMS and PV mounting unchanged
# ---------------------------------------------------------------------------


def test_ctms_paths_remain_under_ctms_prefix(paths: dict[str, dict]) -> None:
    """Every CTMS route stays under ``/api/v1/ctms/...``."""
    ctms_paths = [
        path
        for path, operations in paths.items()
        for op in operations.values()
        if any(tag.startswith("ctms") for tag in op.get("tags", []))
    ]
    assert ctms_paths, "expected at least one CTMS route to be mounted"
    for path in ctms_paths:
        assert path.startswith(f"{API_V1}/ctms/"), (
            f"CTMS route {path!r} is not under the /api/v1/ctms prefix"
        )


def test_pv_paths_remain_under_pv_prefix(paths: dict[str, dict]) -> None:
    """Every PV route stays under ``/api/v1/pv/...``."""
    pv_paths = [path for path in paths if path.startswith(f"{API_V1}/pv")]
    assert pv_paths, "expected at least one PV route to be mounted"
    for path in pv_paths:
        assert path.startswith(f"{API_V1}/pv/"), (
            f"PV route {path!r} is not under the /api/v1/pv prefix"
        )
