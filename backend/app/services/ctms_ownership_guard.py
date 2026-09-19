"""Pre-mutation guards for the CTMS/EDC ownership boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.core.exceptions import ConflictError


class CTMSOwnershipError(ConflictError):
    """Raised when a CTMS command attempts to write EDC-owned state."""

    def __init__(self, *, field: str, operation: str | None = None):
        super().__init__(
            message="CTMS cannot mutate an EDC-owned clinical field",
            details={
                "reason": "EDC_OWNERSHIP_VIOLATION",
                "field": field,
                "operation": operation,
                "authoritative_module": "EDC",
            },
        )
        self.code = "CTMS_OWNERSHIP_CONFLICT"


# Canonical reference IDs are intentionally not in this set.  CTMS may store
# read-only study/site/subject/visit/query references, but it cannot write the
# referenced clinical record or bind/replace its identity.
EDC_OWNED_FIELDS = frozenset(
    {
        "study_version",
        "study_version_id",
        "clinical_configuration",
        "protocol_configuration",
        "ecrf_metadata",
        "clinical_subject",
        "clinical_subject_id",
        "clinical_subject_registry",
        "subject_identity",
        "subject_identifier",
        "subject_number",
        "subject_binding",
        "site_binding",
        "study_version_binding",
        "visit_instance",
        "visit_instance_status",
        "protocol_visit",
        "protocol_visit_definition",
        "protocol_visit_date",
        "visit_date",
        "visit_window",
        "window_status",
        "missed_visit",
        "casebook",
        "form_instance",
        "form_record",
        "field_value",
        "field_values",
        "clinical_data",
        "clinical_note",
        "source_document",
        "query",
        "query_status",
        "query_lifecycle",
        "query_message",
        "query_messages",
        "query_text",
        "quality",
        "quality_signal",
        "data_quality",
        "data_quality_signal",
        "quality_status",
        "attachment",
        "attachments",
        "sdv",
        "sdv_status",
        "clinical_review",
        "review_status",
        "freeze",
        "freeze_status",
        "lock",
        "lock_status",
        "electronic_signature",
        "signature",
        "signature_status",
        "clinical_attachment",
        "clinical_attachments",
        "clinical_export",
        "clinical_exports",
    }
)

# These are accepted as references only.  A key such as ``subject_id`` is not
# a request to create or modify a subject; the resolver separately verifies it
# exists in the EDC registry.
CANONICAL_REFERENCE_FIELDS = frozenset(
    {
        "study_id",
        "site_id",
        "subject_id",
        "visit_instance_id",
        "query_id",
        "edc_study_id",
        "edc_site_id",
        "edc_subject_id",
        "edc_visit_instance_id",
        "edc_query_id",
        "source_study_id",
        "source_site_id",
        "source_subject_id",
        "source_visit_instance_id",
        "source_query_id",
        "canonical_study_id",
        "canonical_site_id",
        "canonical_subject_id",
        "canonical_visit_instance_id",
        "canonical_query_id",
    }
)

# Operation names are checked in addition to payload fields so a command cannot
# bypass the guard with an empty payload (for example, create_subject()).
COMPETING_CLINICAL_OPERATIONS = frozenset(
    {
        "create_study_version",
        "update_study_version",
        "create_subject",
        "create_clinical_subject",
        "replace_subject",
        "update_subject_identity",
        "bind_subject",
        "create_visit_instance",
        "update_visit_instance",
        "create_protocol_visit",
        "create_form_instance",
        "update_form_instance",
        "create_form_record",
        "create_field_value",
        "update_field_value",
        "create_query",
        "update_query",
        "change_query_status",
        "add_query_message",
        "update_sdv",
        "update_review",
        "create_quality",
        "update_quality",
        "update_clinical_quality",
        "freeze_clinical_record",
        "lock_clinical_record",
        "sign_clinical_record",
        "upload_attachment",
        "delete_attachment",
        "upload_clinical_attachment",
        "delete_clinical_attachment",
        "create_clinical_export",
        "update_clinical_export",
    }
)


def normalize_field_name(value: str) -> str:
    """Normalize snake/camel/case variants before ownership comparison."""

    value = value.strip().replace("-", "_").replace(" ", "_")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"_+", "_", value).lower()


def _is_edc_owned_field(field_name: str) -> bool:
    normalized = normalize_field_name(field_name)
    if normalized in CANONICAL_REFERENCE_FIELDS:
        return False
    if normalized in EDC_OWNED_FIELDS:
        return True
    # Catch common nested/qualified forms such as clinical.subject_binding or
    # query.lifecycle without treating approved *_id references as mutations.
    if normalized.endswith("_id") and normalized in CANONICAL_REFERENCE_FIELDS:
        return False
    return any(
        normalized.startswith(prefix + "_") or normalized.endswith("_" + suffix)
        for prefix in (
            "clinical_data",
            "clinical_subject",
            "study_version",
            "visit_instance",
            "protocol_visit",
            "form_instance",
            "field_value",
            "query_message",
            "query_lifecycle",
            "clinical_attachment",
            "clinical_export",
        )
        for suffix in (
            "binding",
            "lifecycle",
            "status",
            "messages",
            "signature",
            "lock",
            "freeze",
        )
    )


def _find_prohibited_field(value: Any, *, path: str = "$") -> str | None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = normalize_field_name(key)
            child_path = f"{path}.{key}"
            if _is_edc_owned_field(normalized):
                return child_path
            # A generic ``subject``, ``visit_instance``, or ``query`` object is
            # a competing clinical payload.  Scalar IDs remain allowed above.
            if normalized in {"subject", "visit_instance", "query", "visit"}:
                return child_path
            found = _find_prohibited_field(child, path=child_path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            found = _find_prohibited_field(child, path=f"{path}[{index}]")
            if found is not None:
                return found
    return None


def assert_ctms_command_safe(
    payload: Mapping[str, Any] | None = None,
    *,
    operation: str | None = None,
) -> None:
    """Reject EDC-owned fields/operations before any service mutation.

    The function is deliberately side-effect free.  Call it before opening a
    CTMS mutation transaction or adding an ORM object to a session.
    """

    normalized_operation = normalize_field_name(operation) if operation else None
    if normalized_operation in COMPETING_CLINICAL_OPERATIONS:
        raise CTMSOwnershipError(field=normalized_operation, operation=normalized_operation)

    field = _find_prohibited_field(payload or {})
    if field is not None:
        raise CTMSOwnershipError(field=field, operation=normalized_operation)


def guard_ctms_command(
    payload: Mapping[str, Any] | None = None,
    *,
    operation: str | None = None,
) -> None:
    """Alias used by route/service code."""

    assert_ctms_command_safe(payload, operation=operation)


def assert_no_competing_clinical_record_creation(
    operation: str, payload: Mapping[str, Any] | None = None
) -> None:
    """Explicitly guard commands that could create a competing clinical record."""

    assert_ctms_command_safe(payload, operation=operation)


__all__ = [
    "CANONICAL_REFERENCE_FIELDS",
    "COMPETING_CLINICAL_OPERATIONS",
    "EDC_OWNED_FIELDS",
    "CTMSOwnershipError",
    "assert_ctms_command_safe",
    "assert_no_competing_clinical_record_creation",
    "guard_ctms_command",
    "normalize_field_name",
]
