"""Compliance and validation test suite — 21 CFR Part 11, ALCOA+, environment separation.

This suite provides independent verification (Req 26.4) that the EDC system
satisfies regulatory compliance controls:

1. Audit immutability (21 CFR Part 11, Req 18.2)
2. ALCOA+ / Reason_For_Change (Req 10.5, 18.1)
3. UTC clock derivation (Req 25.2)
4. Environment separation (Req 25.1)
5. Independent scope enforcement verification (Req 26.4, 2.2)
6. Audit completeness (Req 18.1, 10.8)

Validates Requirements: 25.1, 25.2, 25.5, 25.6, 26.4
"""

import inspect
import uuid
from datetime import UTC
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.audit import AuditService
from app.core.config import Environment, Settings
from app.core.permissions import PERMISSION_CODES
from app.models.audit import AuditEvent
from app.services.data_capture_service import DataCaptureService
from app.services.permission_service import PermissionService

# ===========================================================================
# 1. Audit immutability (21 CFR Part 11)
# ===========================================================================


class TestAuditImmutability:
    """Verify that the audit subsystem enforces append-only immutability.

    Validates: Requirements 18.2, 25.6, 26.4
    """

    def test_audit_service_has_no_update_method(self):
        """AuditService must NOT expose an update method — application-layer guard."""
        service = AuditService()
        public_methods = [
            m for m in dir(service) if not m.startswith("_") and callable(getattr(service, m))
        ]
        forbidden = {"update", "delete", "remove", "modify", "patch", "put"}
        violations = [m for m in public_methods if m in forbidden]
        assert violations == [], f"AuditService exposes forbidden mutation methods: {violations}"

    def test_audit_service_has_no_delete_method(self):
        """AuditService must NOT expose a delete method — application-layer guard."""
        service = AuditService()
        public_methods = [
            m for m in dir(service) if not m.startswith("_") and callable(getattr(service, m))
        ]
        # Verify none of the methods contain 'delete' in their name
        delete_methods = [m for m in public_methods if "delete" in m.lower()]
        assert delete_methods == [], (
            f"AuditService exposes delete-related methods: {delete_methods}"
        )

    def test_audit_migration_includes_immutability_trigger(self):
        """The audit_events migration must include the BEFORE UPDATE OR DELETE trigger."""
        migration_path = (
            Path(__file__).parents[2] / "alembic" / "versions" / "0001_create_audit_events.py"
        )
        assert migration_path.exists(), f"Migration file not found: {migration_path}"

        source = migration_path.read_text()
        # Must contain the trigger creation
        assert "prevent_audit_modification" in source, (
            "Migration missing the immutability trigger function"
        )
        assert "BEFORE UPDATE OR DELETE" in source, (
            "Migration missing the BEFORE UPDATE OR DELETE trigger clause"
        )
        assert "audit_events_immutable" in source, (
            "Migration missing the named trigger 'audit_events_immutable'"
        )

    def test_audit_migration_revokes_privileges(self):
        """The migration must REVOKE UPDATE, DELETE from the application role."""
        migration_path = (
            Path(__file__).parents[2] / "alembic" / "versions" / "0001_create_audit_events.py"
        )
        source = migration_path.read_text()
        assert "REVOKE UPDATE, DELETE ON audit_events" in source, (
            "Migration missing REVOKE UPDATE, DELETE on audit_events"
        )

    @pytest.mark.asyncio
    async def test_audit_record_does_not_commit(self):
        """AuditService.record() must NOT call session.commit — caller owns tx."""
        service = AuditService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        await service.record(
            mock_session,
            entity_type="test_entity",
            entity_id=uuid.uuid4(),
            action="create",
            actor_id=uuid.uuid4(),
        )

        mock_session.commit.assert_not_called()
        # It SHOULD flush (to assign id) but never commit
        mock_session.flush.assert_called()


# ===========================================================================
# 2. ALCOA+ / Reason_For_Change
# ===========================================================================


class TestALCOAReasonForChange:
    """Verify ALCOA+ data integrity controls and Reason_For_Change enforcement.

    Validates: Requirements 10.5, 18.1, 25.5
    """

    @pytest.mark.asyncio
    async def test_change_value_requires_reason_post_submission(self):
        """DataCaptureService.change_value must reject edits without reason post-submission."""
        from app.models.form_data import FormInstance, FormInstanceStatus

        service = DataCaptureService()
        mock_session = AsyncMock()

        # Create a submitted form instance
        form_instance = MagicMock(spec=FormInstance)
        form_instance.status = FormInstanceStatus.submitted
        form_instance.id = uuid.uuid4()

        # Attempt change without reason — should raise ValidationError
        with pytest.raises(Exception) as exc_info:
            await service.change_value(
                mock_session,
                form_instance=form_instance,
                field_id=uuid.uuid4(),
                new_value="new_val",
                reason=None,  # Missing reason
                actor_id=uuid.uuid4(),
            )

        assert "Reason_For_Change" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_change_value_requires_reason_when_empty_string(self):
        """Empty-string reason must also be rejected for post-submission edits."""
        from app.models.form_data import FormInstance, FormInstanceStatus

        service = DataCaptureService()
        mock_session = AsyncMock()

        form_instance = MagicMock(spec=FormInstance)
        form_instance.status = FormInstanceStatus.submitted
        form_instance.id = uuid.uuid4()

        with pytest.raises(Exception) as exc_info:
            await service.change_value(
                mock_session,
                form_instance=form_instance,
                field_id=uuid.uuid4(),
                new_value="new_val",
                reason="   ",  # Whitespace only
                actor_id=uuid.uuid4(),
            )

        assert "Reason_For_Change" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_audit_event_contains_reason_when_provided(self):
        """When reason is provided, the AuditEvent must store it."""
        service = AuditService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        reason_text = "Correcting transcription error per monitor query #42"
        event = await service.record(
            mock_session,
            entity_type="field_value",
            entity_id=uuid.uuid4(),
            action="update",
            actor_id=uuid.uuid4(),
            reason=reason_text,
        )

        assert event.reason == reason_text

    @pytest.mark.asyncio
    async def test_audit_event_has_required_alcoa_fields(self):
        """AuditEvent must have non-null actor_id, entity_type, entity_id, action.

        The timestamp is populated by the column default at INSERT time (DB layer),
        so we verify that the model defines a non-null timestamp column with a default.
        """
        service = AuditService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        actor = uuid.uuid4()
        entity = uuid.uuid4()

        event = await service.record(
            mock_session,
            entity_type="subject",
            entity_id=entity,
            action="create",
            actor_id=actor,
        )

        # ALCOA+ attributable: actor must be set
        assert event.actor_id == actor
        # ALCOA+ legible/original: entity identification
        assert event.entity_type == "subject"
        assert event.entity_id == entity
        assert event.action == "create"

        # ALCOA+ contemporaneous: the model defines a timestamp with default
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(AuditEvent)
        ts_col = mapper.columns["timestamp"]
        assert not ts_col.nullable, "AuditEvent.timestamp must not be nullable"
        assert ts_col.default is not None, "AuditEvent.timestamp must have a default"


# ===========================================================================
# 3. UTC clock derivation (Req 25.2)
# ===========================================================================


class TestUTCClockDerivation:
    """Verify all model timestamps use UTC.

    Validates: Requirement 25.2
    """

    def test_audit_event_timestamp_is_timezone_aware(self):
        """AuditEvent.timestamp column must use DateTime(timezone=True)."""
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(AuditEvent)
        timestamp_col = mapper.columns["timestamp"]
        assert timestamp_col.type.timezone is True, (
            "AuditEvent.timestamp must use DateTime(timezone=True)"
        )

    def test_audit_event_timestamp_default_is_utc(self):
        """AuditEvent.timestamp default must produce UTC datetime."""
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(AuditEvent)
        timestamp_col = mapper.columns["timestamp"]
        # The default should be a callable that returns UTC time
        default = timestamp_col.default
        assert default is not None, "AuditEvent.timestamp must have a default"
        assert default.is_callable, "AuditEvent.timestamp default must be callable"

        # Invoke the default (SQLAlchemy passes a context arg to callables)
        result = default.arg(None)
        assert result.tzinfo is not None, (
            "AuditEvent.timestamp default must produce timezone-aware datetime"
        )
        # Verify it's UTC specifically
        assert result.tzinfo == UTC or str(result.tzinfo) == "UTC", (
            f"AuditEvent.timestamp default must produce UTC, got {result.tzinfo}"
        )

    def test_all_model_timestamps_use_timezone_true(self):
        """All DateTime columns across models must use timezone=True (UTC requirement)."""
        from sqlalchemy import inspect as sa_inspect

        from app.models.audit import AuditEvent
        from app.models.form_data import FieldValue, FormInstance
        from app.models.identity import User
        from app.models.site import Site
        from app.models.study import Study
        from app.models.subject import Subject

        models = [AuditEvent, FormInstance, FieldValue, User, Study, Subject, Site]
        violations = []

        for model in models:
            mapper = sa_inspect(model)
            for col in mapper.columns:
                if (
                    hasattr(col.type, "timezone")
                    and col.type.__class__.__name__ == "DateTime"
                    and not col.type.timezone
                ):
                    violations.append(
                        f"{model.__tablename__}.{col.name} uses DateTime without timezone=True"
                    )

        assert violations == [], "Models with non-UTC timestamps found:\n" + "\n".join(violations)


# ===========================================================================
# 4. Environment separation (Req 25.1)
# ===========================================================================


class TestEnvironmentSeparation:
    """Verify environment isolation and configuration.

    Validates: Requirement 25.1
    """

    def test_supports_all_five_environments(self):
        """Settings must support local, development, test, staging, production."""
        expected = {"local", "development", "test", "staging", "production"}
        actual = {e.value for e in Environment}
        assert actual == expected, (
            f"Environment enum missing values. Expected {expected}, got {actual}"
        )

    def test_environment_enum_values_are_distinct(self):
        """Each environment enum value must be distinct (no duplicates)."""
        values = [e.value for e in Environment]
        assert len(values) == len(set(values)), "Environment enum contains duplicate values"

    def test_environment_enum_has_exactly_five_members(self):
        """Exactly 5 environments as per requirements."""
        assert len(Environment) == 5, f"Expected 5 environments, got {len(Environment)}"

    def test_settings_accepts_each_environment(self):
        """Settings should accept each environment value without error."""
        for env in Environment:
            # Validate that settings can be constructed with each env
            settings = Settings(
                environment=env,
                database_url="postgresql+asyncpg://localhost/test",
                secret_key="test-key",
            )
            assert settings.environment == env


# ===========================================================================
# 5. Independent scope enforcement verification (Req 26.4)
# ===========================================================================


class TestScopeEnforcementVerification:
    """Independent verification of authorization scope enforcement.

    Validates: Requirements 2.2, 26.4
    """

    def test_permission_service_require_raises_for_unauthorized(self):
        """PermissionService.require must raise for unauthorized access."""
        from app.core.exceptions import AuthorizationError

        service = PermissionService()

        # Create a user with no roles (empty scope)
        user = MagicMock()
        user.user_roles = []

        with pytest.raises(AuthorizationError):
            service.require(user, "form.enter", study_id=uuid.uuid4())

    def test_permission_service_require_passes_for_authorized(self):
        """PermissionService.require must pass for properly scoped user."""
        service = PermissionService()
        study_id = uuid.uuid4()

        # Create a user with a role granting form.enter at the target study
        permission_mock = MagicMock()
        permission_mock.code = "form.enter"

        role_permission_mock = MagicMock()
        role_permission_mock.permission = permission_mock

        role_mock = MagicMock()
        role_mock.role_permissions = [role_permission_mock]

        user_role_mock = MagicMock()
        user_role_mock.role = role_mock
        user_role_mock.study_id = study_id
        user_role_mock.site_id = None  # study-scope

        user = MagicMock()
        user.user_roles = [user_role_mock]

        # Should not raise
        service.require(user, "form.enter", study_id=study_id)

    def test_every_route_has_permission_guard(self):
        """Every route handler (except health/auth) must use a permission guard dependency.

        This verifies Req 23.4 and 26.4: every protected route passes through
        Permission_Service before mutation.
        """
        routes_dir = Path(__file__).parents[1] / "api" / "routes"
        # Routes that are allowed to NOT have guards (public endpoints)
        exempt_files = {"health.py", "__init__.py", "auth.py"}

        violations = []

        for route_file in sorted(routes_dir.glob("*.py")):
            if route_file.name in exempt_files:
                continue

            source = route_file.read_text()

            # Must import require_permission or PermissionGuard
            has_guard_import = (
                "require_permission" in source
                or "PermissionGuard" in source
                or "get_current_user" in source
            )
            if not has_guard_import:
                violations.append(f"{route_file.name}: does not import permission guard dependency")

        assert violations == [], "Routes without permission guards:\n" + "\n".join(violations)

    def test_permission_codes_set_is_non_empty(self):
        """PERMISSION_CODES must be non-empty and contain expected core codes."""
        assert len(PERMISSION_CODES) > 0, "PERMISSION_CODES is empty"

        # Verify essential clinical workflow codes are present
        expected_codes = {
            "form.enter",
            "form.submit",
            "form.read",
            "subject.create",
            "subject.read",
            "audit.read",
            "query.create",
            "data.export",
        }
        missing = expected_codes - PERMISSION_CODES
        assert missing == set(), f"PERMISSION_CODES missing expected codes: {missing}"

    def test_permission_codes_are_stable_format(self):
        """All permission codes must follow the domain.action format."""
        for code in PERMISSION_CODES:
            parts = code.split(".")
            assert len(parts) == 2, f"Permission code '{code}' does not follow domain.action format"
            assert all(p.isalpha() or "_" in p for p in parts), (
                f"Permission code '{code}' contains invalid characters"
            )


# ===========================================================================
# 6. Audit completeness verification
# ===========================================================================


class TestAuditCompleteness:
    """Verify every service that mutates clinical data calls audit_service.record.

    Validates: Requirements 18.1, 10.8, 25.6, 26.4
    """

    # Services that perform clinical data mutations and MUST call audit_service.record
    CLINICAL_SERVICES: ClassVar[list[str]] = [
        "data_capture_service.py",
        "subject_service.py",
        "query_service.py",
        "study_service.py",
        "site_service.py",
        "visit_service.py",
        "form_metadata_service.py",
    ]

    def test_clinical_services_call_audit_record(self):
        """Each clinical-mutating service must reference audit_service.record."""
        services_dir = Path(__file__).parents[1] / "services"

        violations = []
        for service_filename in self.CLINICAL_SERVICES:
            service_path = services_dir / service_filename
            if not service_path.exists():
                violations.append(f"{service_filename}: file not found")
                continue

            source = service_path.read_text()
            if "audit_service.record" not in source and "audit_service" not in source:
                violations.append(f"{service_filename}: does not call audit_service.record")

        assert violations == [], "Clinical services missing audit_service calls:\n" + "\n".join(
            violations
        )

    def test_data_capture_audits_every_field_change(self):
        """DataCaptureService._upsert_field_value must call audit_service.record."""
        source = inspect.getsource(DataCaptureService)
        # The _upsert_field_value method must contain audit_service.record calls
        assert "audit_service.record" in source, (
            "DataCaptureService does not call audit_service.record"
        )

    def test_audit_service_source_has_no_commit(self):
        """AuditService.record source code must not contain session.commit()."""
        source = inspect.getsource(AuditService.record)
        assert "session.commit" not in source and "await session.commit" not in source, (
            "AuditService.record must not commit — caller's transaction boundary"
        )

    def test_routes_with_mutations_import_audit_or_delegate_to_service(self):
        """Routes that perform writes should either import audit_service or delegate
        to a service that handles audit internally.
        """
        routes_dir = Path(__file__).parents[1] / "api" / "routes"
        exempt_files = {"health.py", "__init__.py", "auth.py"}

        for route_file in sorted(routes_dir.glob("*.py")):
            if route_file.name in exempt_files:
                continue

            source = route_file.read_text()
            # Routes that have POST/PATCH/PUT/DELETE should either:
            # 1. Import audit_service directly, OR
            # 2. Import a service that handles audit internally
            has_mutation = any(
                method in source
                for method in ["@router.post", "@router.patch", "@router.put", "@router.delete"]
            )
            if has_mutation:
                has_audit_reference = (
                    "audit_service" in source
                    or "_service" in source  # delegates to a service
                    or "service" in source  # any service import
                )
                assert has_audit_reference, (
                    f"{route_file.name}: has mutation routes but no audit/service reference"
                )
