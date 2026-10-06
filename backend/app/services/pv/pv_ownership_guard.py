"""Pre-mutation guards for the PV/EDC and PV/CTMS ownership boundaries.

Every PV command is checked before any PV service opens a mutation transaction
or adds an ORM object to a session. A command that carries an EDC-owned clinical
field, a CTMS-owned operational field, or targets another module's record is
rejected before any module's authoritative or audit state changes
(Requirements 16.6, 23.4, 23.5).

PV may store read-only canonical references (``study_id``, ``site_id``,
``subject_reference``, ``visit_instance_id``, ...). A reference is not a request
to create or mutate the referenced record; the PV identity resolver separately
verifies each reference exists in canonical/EDC identity.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.core.exceptions import ConflictError


class PVOwnershipError(ConflictError):
    """Raised when a PV command attempts to write an EDC- or CTMS-owned field."""

    def __init__(
        self,
        *,
        field: str,
        authoritative_module: str,
        operation: str | None = None,
    ):
        super().__init__(
            message=(
                f"PV cannot mutate a {authoritative_module}-owned "
                f"{'clinical' if authoritative_module == 'EDC' else 'operational'} field"
            ),
            details={
                "reason": (
                    "EDC_OWNERSHIP_VIOLATION"
                    if authoritative_module == "EDC"
                    else "CTMS_OWNERSHIP_VIOLATION"
                ),
                "field": field,
                "operation": operation,
                "authoritative_module": authoritative_module,
            },
        )
        self.code = "PV_OWNERSHIP_CONFLICT"


# Canonical reference IDs are intentionally not owned here. PV may store
# read-only study/site/subject/visit references, but it cannot write the
# referenced clinical/operational record or bind/replace its identity.
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
        "sdv",
        "sdv_status",
        "clinical_review",
        "review_status",
        "freeze",
        "freeze_status",
        "lock",
        "lock_status",
        "clinical_signature",
        "clinical_electronic_signature",
        "clinical_attachment",
        "clinical_attachments",
        "clinical_export",
        "clinical_exports",
    }
)

# CTMS-owned operational fields PV must never write (Requirement 23.5).
CTMS_OWNED_FIELDS = frozenset(
    {
        "operational_study",
        "operational_study_profile",
        "operational_site",
        "operational_site_profile",
        "operational_site_status",
        "site_readiness",
        "site_activation",
        "site_contact",
        "operational_contact",
        "enrollment",
        "enrollment_target",
        "enrollment_milestone",
        "operational_milestone",
        "monitoring_plan",
        "monitoring_activity",
        "monitoring_visit",
        "work_item",
        "work_task",
        "task_assignment",
        "operational_attachment",
        "operational_attachments",
        "operational_export",
        "operational_exports",
    }
)


# These are accepted as references only. A key such as ``subject_reference`` is
# not a request to create or modify a subject; the resolver separately verifies
# it exists in canonical/EDC identity.
CANONICAL_REFERENCE_FIELDS = frozenset(
    {
        "study_id",
        "site_id",
        "subject_id",
        "subject_reference",
        "visit_instance_id",
        "query_id",
        "edc_study_id",
        "edc_site_id",
        "edc_subject_id",
        "edc_subject_reference",
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
        "canonical_subject_reference",
        "canonical_visit_instance_id",
        "canonical_query_id",
    }
)

# EDC clinical operations PV must never perform, even with an empty payload.
COMPETING_CLINICAL_OPERATIONS = frozenset(
    {
        "create_study_version",
        "update_study_version",
        "create_subject",
        "create_clinical_subject",
        "allocate_subject",
        "allocate_subject_identifier",
        "replace_subject",
        "update_subject_identity",
        "bind_subject",
        "initialize_casebook",
        "create_visit_instance",
        "update_visit_instance",
        "create_protocol_visit",
        "mutate_protocol_visit",
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
        "freeze_clinical_record",
        "lock_clinical_record",
        "sign_clinical_record",
        "upload_clinical_attachment",
        "delete_clinical_attachment",
        "create_clinical_export",
        "update_clinical_export",
    }
)

# CTMS operational operations PV must never perform.
COMPETING_OPERATIONAL_OPERATIONS = frozenset(
    {
        "create_operational_study",
        "update_operational_study",
        "create_operational_site",
        "update_operational_site",
        "update_operational_site_status",
        "activate_site",
        "record_operational_milestone",
        "update_enrollment",
        "update_enrollment_target",
        "create_monitoring_plan",
        "update_monitoring_plan",
        "schedule_monitoring_activity",
        "create_work_item",
        "update_work_item",
        "assign_task",
        "upload_operational_attachment",
        "delete_operational_attachment",
        "create_operational_export",
        "update_operational_export",
    }
)

# Generic clinical/operational object keys that always denote a competing
# payload regardless of their contents.
_COMPETING_OBJECT_KEYS = frozenset(
    {"subject", "visit_instance", "visit", "query", "form_instance", "form_record"}
)


def normalize_field_name(value: str) -> str:
    """Normalize snake/camel/case variants before ownership comparison."""

    value = value.strip().replace("-", "_").replace(" ", "_")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"_+", "_", value).lower()


def _owning_module_for_field(field_name: str) -> str | None:
    """Return "EDC"/"CTMS" if the field is owned by another module, else None."""

    normalized = normalize_field_name(field_name)
    if normalized in CANONICAL_REFERENCE_FIELDS:
        return None
    if normalized in EDC_OWNED_FIELDS:
        return "EDC"
    if normalized in CTMS_OWNED_FIELDS:
        return "CTMS"
    # Catch common nested/qualified EDC forms such as clinical.subject_binding
    # or query.lifecycle without treating approved *_id references as mutations.
    edc_nested = any(
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
    if edc_nested:
        return "EDC"
    return None


def _find_prohibited_field(
    value: Any, *, path: str = "$"
) -> tuple[str, str] | None:
    """Return ``(path, authoritative_module)`` for the first prohibited field."""

    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = normalize_field_name(key)
            child_path = f"{path}.{key}"
            owner = _owning_module_for_field(normalized)
            if owner is not None:
                return child_path, owner
            # A generic clinical object is a competing clinical payload; scalar
            # canonical IDs remain allowed above.
            if normalized in _COMPETING_OBJECT_KEYS:
                return child_path, "EDC"
            found = _find_prohibited_field(child, path=child_path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            found = _find_prohibited_field(child, path=f"{path}[{index}]")
            if found is not None:
                return found
    return None


def assert_pv_command_safe(
    payload: Mapping[str, Any] | None = None,
    *,
    operation: str | None = None,
) -> None:
    """Reject EDC-/CTMS-owned fields and operations before any PV mutation.

    The function is deliberately side-effect free. Call it before opening a PV
    mutation transaction or adding an ORM object to a session, so a rejected
    command changes no PV safety state and no audit state.
    """

    normalized_operation = normalize_field_name(operation) if operation else None
    if normalized_operation in COMPETING_CLINICAL_OPERATIONS:
        raise PVOwnershipError(
            field=normalized_operation,
            authoritative_module="EDC",
            operation=normalized_operation,
        )
    if normalized_operation in COMPETING_OPERATIONAL_OPERATIONS:
        raise PVOwnershipError(
            field=normalized_operation,
            authoritative_module="CTMS",
            operation=normalized_operation,
        )

    prohibited = _find_prohibited_field(payload or {})
    if prohibited is not None:
        field, owner = prohibited
        raise PVOwnershipError(
            field=field,
            authoritative_module=owner,
            operation=normalized_operation,
        )


def guard_pv_command(
    payload: Mapping[str, Any] | None = None,
    *,
    operation: str | None = None,
) -> None:
    """Alias used by PV route/service code."""

    assert_pv_command_safe(payload, operation=operation)


def assert_no_edc_subject_or_visit_mutation(
    operation: str, payload: Mapping[str, Any] | None = None
) -> None:
    """Explicitly guard commands that could create/allocate/mutate a clinical
    subject or protocol visit (Requirement 3.10, 23.3)."""

    assert_pv_command_safe(payload, operation=operation)


__all__ = [
    "CANONICAL_REFERENCE_FIELDS",
    "COMPETING_CLINICAL_OPERATIONS",
    "COMPETING_OPERATIONAL_OPERATIONS",
    "CTMS_OWNED_FIELDS",
    "EDC_OWNED_FIELDS",
    "PVOwnershipError",
    "assert_no_edc_subject_or_visit_mutation",
    "assert_pv_command_safe",
    "guard_pv_command",
    "normalize_field_name",
]
