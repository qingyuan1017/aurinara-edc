"""Tests for permission guard dependencies in api/deps.py.

Validates Requirements: 2.2, 2.3, 23.1, 23.4
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from app.api.deps import (
    CTMSPermissionGuard,
    PermissionGuard,
    _extract_uuid,
    get_permission_service,
    require_ctms_permission,
    require_permission,
)
from app.core.exceptions import AuthorizationError
from app.services.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Lightweight stubs
# ---------------------------------------------------------------------------

STUDY_A = uuid.uuid4()
STUDY_B = uuid.uuid4()
SITE_1 = uuid.uuid4()
SITE_2 = uuid.uuid4()


@dataclass
class StubPermission:
    code: str
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubRolePermission:
    permission: StubPermission
    role_id: UUID = field(default_factory=uuid.uuid4)
    permission_id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubRole:
    name: str
    scope_level: str
    role_permissions: list[StubRolePermission] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubUserRole:
    role: StubRole
    study_id: UUID | None = None
    site_id: UUID | None = None
    user_id: UUID = field(default_factory=uuid.uuid4)
    role_id: UUID = field(default_factory=uuid.uuid4)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubUser:
    user_roles: list[StubUserRole] = field(default_factory=list)
    id: UUID = field(default_factory=uuid.uuid4)
    email: str = "test@example.com"
    status: str = "active"


@dataclass
class StubRequest:
    """Minimal stub for a FastAPI Request with path_params and query_params."""

    path_params: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_site_coordinator(study_id: UUID, site_id: UUID) -> StubUser:
    perms = [
        StubRolePermission(permission=StubPermission(code="form.enter")),
        StubRolePermission(permission=StubPermission(code="form.submit")),
    ]
    role = StubRole(name="Site Coordinator", scope_level="site", role_permissions=perms)
    user_role = StubUserRole(role=role, study_id=study_id, site_id=site_id)
    return StubUser(user_roles=[user_role])


def _make_system_admin() -> StubUser:
    perms = [
        StubRolePermission(permission=StubPermission(code="user.list")),
        StubRolePermission(permission=StubPermission(code="study.create")),
        StubRolePermission(permission=StubPermission(code="form.enter")),
    ]
    role = StubRole(name="System Administrator", scope_level="system", role_permissions=perms)
    user_role = StubUserRole(role=role, study_id=None, site_id=None)
    return StubUser(user_roles=[user_role])


def _make_ctms_operator(study_id: UUID, site_id: UUID) -> StubUser:
    role = StubRole(
        name="CTMS_Operations_User",
        scope_level="study",
        role_permissions=[
            StubRolePermission(
                permission=StubPermission(
                    code="ctms.operational_study_management"
                )
            )
        ],
    )
    return StubUser(user_roles=[StubUserRole(role=role, study_id=study_id, site_id=site_id)])


# ---------------------------------------------------------------------------
# Tests: _extract_uuid
# ---------------------------------------------------------------------------


class TestExtractUuid:
    """Tests for _extract_uuid helper."""

    def test_extracts_from_path_params(self):
        request = StubRequest(path_params={"study_id": str(STUDY_A)})
        result = _extract_uuid(request, "study_id")
        assert result == STUDY_A

    def test_extracts_from_query_params(self):
        request = StubRequest(query_params={"site_id": str(SITE_1)})
        result = _extract_uuid(request, "site_id")
        assert result == SITE_1

    def test_path_params_take_precedence(self):
        request = StubRequest(
            path_params={"study_id": str(STUDY_A)},
            query_params={"study_id": str(STUDY_B)},
        )
        result = _extract_uuid(request, "study_id")
        assert result == STUDY_A

    def test_returns_none_when_missing(self):
        request = StubRequest()
        result = _extract_uuid(request, "study_id")
        assert result is None

    def test_returns_none_for_invalid_uuid(self):
        request = StubRequest(path_params={"study_id": "not-a-uuid"})
        result = _extract_uuid(request, "study_id")
        assert result is None

    def test_handles_uuid_object_in_path(self):
        """Path params may be UUID objects directly."""
        request = StubRequest(path_params={"study_id": STUDY_A})
        result = _extract_uuid(request, "study_id")
        assert result == STUDY_A


# ---------------------------------------------------------------------------
# Tests: get_permission_service
# ---------------------------------------------------------------------------


class TestGetPermissionService:
    """Tests for get_permission_service dependency."""

    def test_returns_permission_service_instance(self):
        svc = get_permission_service()
        assert isinstance(svc, PermissionService)

    def test_returns_singleton(self):
        svc1 = get_permission_service()
        svc2 = get_permission_service()
        assert svc1 is svc2


# ---------------------------------------------------------------------------
# Tests: require_permission
# ---------------------------------------------------------------------------


class TestRequirePermission:
    """Tests for require_permission factory dependency."""

    @pytest.mark.asyncio
    async def test_passes_with_valid_permission(self):
        """User with correct permission at correct scope passes."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        svc = PermissionService()

        guard = require_permission("form.enter")
        result = await guard(request=request, current_user=user, permission_service=svc)
        assert result is user

    @pytest.mark.asyncio
    async def test_raises_on_missing_permission(self):
        """User without the required permission gets 403."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        svc = PermissionService()

        guard = require_permission("audit.read")
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(request=request, current_user=user, permission_service=svc)
        assert exc_info.value.details["required_permission"] == "audit.read"

    @pytest.mark.asyncio
    async def test_raises_on_wrong_scope(self):
        """User with correct permission but wrong scope gets 403."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_2)}
        )
        svc = PermissionService()

        guard = require_permission("form.enter")
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(request=request, current_user=user, permission_service=svc)
        assert exc_info.value.details["site_id"] == str(SITE_2)

    @pytest.mark.asyncio
    async def test_system_admin_passes_any_scope(self):
        """System admin passes for any study/site."""
        user = _make_system_admin()
        request = StubRequest(
            path_params={"study_id": str(STUDY_B), "site_id": str(SITE_2)}
        )
        svc = PermissionService()

        guard = require_permission("form.enter")
        result = await guard(request=request, current_user=user, permission_service=svc)
        assert result is user

    @pytest.mark.asyncio
    async def test_works_without_scope_params(self):
        """Guard works when no study_id/site_id in request (system-level routes)."""
        user = _make_system_admin()
        request = StubRequest()
        svc = PermissionService()

        guard = require_permission("user.list")
        result = await guard(request=request, current_user=user, permission_service=svc)
        assert result is user


# ---------------------------------------------------------------------------
# Tests: CTMS permission guards
# ---------------------------------------------------------------------------


class TestCTMSPermissionGuard:
    """CTMS uses the same scoped guard and baseline authorization errors."""

    @pytest.mark.asyncio
    async def test_requirement_name_alias_is_enforced_at_scope(self):
        user = _make_ctms_operator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        result = await require_ctms_permission("operational-study-management")(
            request=request,
            current_user=user,
            permission_service=PermissionService(),
        )
        assert result is user

    @pytest.mark.asyncio
    async def test_out_of_scope_ctms_mutation_keeps_baseline_error(self):
        user = _make_ctms_operator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_B), "site_id": str(SITE_1)}
        )
        with pytest.raises(AuthorizationError) as exc_info:
            await CTMSPermissionGuard("operational-study-management")(
                request=request,
                current_user=user,
                permission_service=PermissionService(),
            )
        assert exc_info.value.details["required_permission"] == "operational-study-management"



class TestPermissionGuard:
    """Tests for the PermissionGuard class-based dependency."""

    @pytest.mark.asyncio
    async def test_passes_with_valid_permission(self):
        """User with correct permission at correct scope passes."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        svc = PermissionService()

        guard = PermissionGuard("form.enter")
        result = await guard(
            request=request, current_user=user, permission_service=svc
        )
        assert result is user

    @pytest.mark.asyncio
    async def test_raises_on_missing_permission(self):
        """User without the required permission gets 403."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        svc = PermissionService()

        guard = PermissionGuard("audit.read")
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(
                request=request, current_user=user, permission_service=svc
            )
        assert exc_info.value.details["required_permission"] == "audit.read"

    @pytest.mark.asyncio
    async def test_raises_on_wrong_scope(self):
        """User with permission at wrong site gets 403."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            path_params={"study_id": str(STUDY_B), "site_id": str(SITE_1)}
        )
        svc = PermissionService()

        guard = PermissionGuard("form.enter")
        with pytest.raises(AuthorizationError) as exc_info:
            await guard(
                request=request, current_user=user, permission_service=svc
            )
        assert exc_info.value.details["study_id"] == str(STUDY_B)

    @pytest.mark.asyncio
    async def test_extracts_scope_from_query_params(self):
        """Guard falls back to query params for study_id/site_id."""
        user = _make_site_coordinator(STUDY_A, SITE_1)
        request = StubRequest(
            query_params={"study_id": str(STUDY_A), "site_id": str(SITE_1)}
        )
        svc = PermissionService()

        guard = PermissionGuard("form.enter")
        result = await guard(
            request=request, current_user=user, permission_service=svc
        )
        assert result is user

    @pytest.mark.asyncio
    async def test_system_admin_passes_any_scope(self):
        """System admin passes for any study/site context."""
        user = _make_system_admin()
        request = StubRequest(
            path_params={"study_id": str(STUDY_B), "site_id": str(SITE_2)}
        )
        svc = PermissionService()

        guard = PermissionGuard("study.create")
        result = await guard(
            request=request, current_user=user, permission_service=svc
        )
        assert result is user

    @pytest.mark.asyncio
    async def test_stores_permission_attribute(self):
        """PermissionGuard stores the permission code."""
        guard = PermissionGuard("form.enter")
        assert guard.permission == "form.enter"
