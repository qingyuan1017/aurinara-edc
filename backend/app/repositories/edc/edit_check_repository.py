"""Backward-compatible shim for the moved edit-check repository.

The ``EditCheckRepository`` was reassigned to the Designer module
(``app.repositories.designer.edit_check_repository``) as part of the Designer /
EDC refactor (R5, R11.1). This module re-exports it so existing imports
(``from app.repositories.edc.edit_check_repository import EditCheckRepository``)
keep working unchanged.
"""

from __future__ import annotations

from app.repositories.designer.edit_check_repository import EditCheckRepository

__all__ = ["EditCheckRepository"]
