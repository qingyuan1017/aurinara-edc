"""Focused tests for the CTMS phase scaffold and shared contracts."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.capabilities import get_ctms_capability_manifest
from app.core.config import Settings
from app.core.ctms import (
    CorrelationIdentifier,
    CTMSPhase,
    IdempotencyKey,
    Module,
    OwnershipState,
    build_ctms_manifest,
    ensure_utc,
)


def test_phase_three_manifest_contains_all_prior_phase_capabilities() -> None:
    manifest = build_ctms_manifest(enabled=True, phase=3)

    assert manifest.module is Module.CTMS
    assert manifest.phase is CTMSPhase.PHASE_3
    assert manifest.enabled is True
    assert manifest.supports("operational_studies")
    assert manifest.supports("operational_exports")
    assert manifest.as_dict()["module"] == "CTMS"


def test_disabled_manifest_advertises_no_capabilities_and_preserves_data_contract() -> None:
    manifest = build_ctms_manifest(enabled=False, phase=3)

    assert manifest.enabled is False
    assert manifest.capabilities == ()
    assert manifest.supports("operational_studies") is False


def test_settings_phase_flag_drives_server_manifest() -> None:
    settings = Settings(ctms_enabled=False, ctms_phase=2)

    manifest = get_ctms_capability_manifest(settings)

    assert manifest.enabled is False
    assert manifest.phase is CTMSPhase.PHASE_2


def test_shared_identifiers_and_ownership_states_are_distinct_contracts() -> None:
    correlation_id = CorrelationIdentifier("request-correlation-1")
    idempotency_key = IdempotencyKey("operation-1")

    assert str(correlation_id) == "request-correlation-1"
    assert str(idempotency_key) == "operation-1"
    assert Module.EDC is not Module.CTMS
    assert OwnershipState.PROJECTED.value == "projected"


def test_utc_helper_rejects_naive_and_normalizes_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone"):
        ensure_utc(datetime(2026, 1, 1))

    offset_timestamp = datetime(2026, 1, 1, 4, 0, tzinfo=UTC) - timedelta(hours=1)
    normalized = ensure_utc(offset_timestamp)

    assert normalized.tzinfo is UTC


def test_environment_metadata_excludes_secret_values() -> None:
    settings = Settings(
        environment_namespace="staging-a",
        secrets_namespace="staging-a",
        object_storage_namespace="staging-a",
        auth_issuer="https://issuer.example",
        s3_secret_access_key="do-not-publish",
    )

    metadata = settings.environment_metadata

    assert metadata["namespace"] == "staging-a"
    assert metadata["object_storage_namespace"] == "staging-a"
    assert metadata["auth_configured"] is True
    assert "database_url" not in metadata
    assert "s3_secret_access_key" not in metadata
    assert "do-not-publish" not in str(metadata)
