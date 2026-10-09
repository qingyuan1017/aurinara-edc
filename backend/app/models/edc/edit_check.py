"""Backward-compatible shim for the moved edit-check models.

``EditCheck`` and ``ValidationResult`` were reassigned to the Designer module
(``app.models.designer.edit_check``) as part of the Designer / EDC refactor
(R5, R11.1). They are re-exported here so existing imports
(``from app.models.edc.edit_check import EditCheck, ValidationResult``) keep
working unchanged — an additive move with no table/column renames.
"""

from __future__ import annotations

from app.models.designer.edit_check import EditCheck, ValidationResult

__all__ = ["EditCheck", "ValidationResult"]
