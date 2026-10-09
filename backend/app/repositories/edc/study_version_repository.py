"""Backward-compatible shim for the moved study-version repository.

The ``StudyVersionRepository`` was reassigned to the Designer module
(``app.repositories.designer.study_version_repository``) as part of the
Designer / EDC refactor (R2, R11.1). This module re-exports it so existing
imports (``from app.repositories.edc.study_version_repository import
StudyVersionRepository``) keep working unchanged.
"""

from __future__ import annotations

from app.repositories.designer.study_version_repository import StudyVersionRepository

__all__ = ["StudyVersionRepository"]
