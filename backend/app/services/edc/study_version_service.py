"""Backward-compatible shim for the moved study-version service.

The ``StudyVersionService`` (the Design_Version lifecycle) was reassigned to the
Designer module (``app.services.designer.study_version_service``) as part of the
Designer / EDC refactor (R2, R11.1). This module re-exports the service class,
the module-level singleton, and ``audit_service`` so existing imports
(``from app.services.edc.study_version_service import study_version_service``)
and existing audit patch targets keep working unchanged.
"""

from __future__ import annotations

from app.services.designer.study_version_service import (
    AMENDMENT_REASON_MAX_LENGTH,
    StudyVersionService,
    audit_service,
    study_version_service,
)

__all__ = [
    "AMENDMENT_REASON_MAX_LENGTH",
    "StudyVersionService",
    "audit_service",
    "study_version_service",
]
