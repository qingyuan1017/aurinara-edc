"""Backward-compatible shim for the moved edit-check service.

The Edit_Check_Engine service was reassigned to the Designer module
(``app.services.designer.edit_check_service``) as part of the Designer / EDC
refactor (R5, R11.1). This module re-exports the public surface so existing
imports (``from app.services.edc.edit_check_service import edit_check_service``)
keep working unchanged.
"""

from __future__ import annotations

# ``query_service`` is re-exported as the mutable query-service integration
# point used by tests that patch
# ``app.services.edc.edit_check_service.query_service``.
from app.services.designer.edit_check_service import (
    EditCheckService,
    RuleTestResult,
    edit_check_service,
    query_service,
    seed_example_edit_checks,
)

__all__ = [
    "EditCheckService",
    "RuleTestResult",
    "edit_check_service",
    "query_service",
    "seed_example_edit_checks",
]
