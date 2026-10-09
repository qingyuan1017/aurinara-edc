"""Standard eCRF form template seeding — backward-compatible re-export.

The form template seeder was reassigned to the Designer module and now lives in
``app.services.designer.form_templates``. ``seed_standard_forms`` and
``STANDARD_FORMS`` are re-exported here so existing import paths
(``from app.services.edc.form_templates import seed_standard_forms``) keep
working unchanged (R11.1 — additive, no breakage).

New code should import from ``app.services.designer.form_templates``.
"""

from app.services.designer.form_templates import (
    STANDARD_FORMS,
    seed_standard_forms,
)

__all__ = [
    "STANDARD_FORMS",
    "seed_standard_forms",
]
