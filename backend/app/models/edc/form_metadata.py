"""Form metadata models — backward-compatible re-exports.

The design-time form structure (``FormDefinition``, ``FormSection``,
``FieldDefinition``) was reassigned to the Designer module and now lives in
``app.models.designer.form_metadata``. The code lists (``Codelist``,
``CodelistItem``) were likewise reassigned to the Designer module and now live
in ``app.models.designer.codelist``.

All of these symbols are re-exported here so existing import paths
(``from app.models.edc.form_metadata import FormDefinition, Codelist``) keep
working unchanged (R11.1 — additive, no breakage). Code reading this module
continues to see the same symbols.

Satisfies Requirements:
  - 4.1 / 4.2: form/section/field definitions (now Designer-owned; re-exported).
  - 6.1 / 6.4: code lists and items (now Designer-owned; re-exported).
  - 11.1: Ownership reassignment without table/column renames (stored values
          preserved); FK to ``study_versions`` kept.
"""

# Code lists are owned by the Designer module. Re-exported here for backward
# compatibility with existing ``app.models.edc.form_metadata`` imports and so
# the shared ORM registry resolves relationships (e.g. ``FieldDefinition
# .codelist``) by name.
from app.models.designer.codelist import (
    Codelist,
    CodelistItem,
)

# Form/section/field definitions are owned by the Designer module. Re-exported
# here for backward compatibility with existing ``app.models.edc.form_metadata``
# imports and so the shared ORM registry resolves relationships by name.
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
    JSONBType,
)

# Backward-compatible public surface. ``FormDefinition`` / ``FormSection`` /
# ``FieldDefinition`` are owned by ``app.models.designer.form_metadata`` and
# ``Codelist`` / ``CodelistItem`` by ``app.models.designer.codelist``; both are
# re-exported here.
__all__ = [
    "Codelist",
    "CodelistItem",
    "FieldDefinition",
    "FormDefinition",
    "FormSection",
    "JSONBType",
]
