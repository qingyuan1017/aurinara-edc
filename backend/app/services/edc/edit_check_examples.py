"""Backward-compatible shim for the moved edit-check examples seeder.

The example edit-check seeder was reassigned to the Designer module
(``app.services.designer.edit_check_examples``) as part of the Designer / EDC
refactor (R5, R11.1). This module re-exports the public surface so existing
imports (``from app.services.edc.edit_check_examples import ...``) keep working
unchanged.
"""

from __future__ import annotations

from app.services.designer.edit_check_examples import (
    EXAMPLE_EDIT_CHECKS,
    seed_example_edit_checks,
)

__all__ = ["EXAMPLE_EDIT_CHECKS", "seed_example_edit_checks"]
