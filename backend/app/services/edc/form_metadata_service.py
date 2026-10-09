"""Form_Metadata_Service — backward-compatible re-export.

The Form_Metadata_Service was reassigned to the Designer module and now lives in
``app.services.designer.form_metadata_service``. The service class and its
module-level singleton are re-exported here so existing import paths
(``from app.services.edc.form_metadata_service import form_metadata_service``)
keep working unchanged (R11.1 — additive, no breakage).

New code should import from ``app.services.designer.form_metadata_service``.
"""

from app.services.designer.form_metadata_service import (
    FormMetadataService,
    form_metadata_service,
)

__all__ = [
    "FormMetadataService",
    "form_metadata_service",
]
