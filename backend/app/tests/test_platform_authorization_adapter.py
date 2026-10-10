from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AuthorizationError, ServiceUnavailableError
from app.services.shared.permission_service import PermissionService
from app.services.shared.platform_authorization import PlatformDecision


@dataclass
class Permission:
    code: str


@dataclass
class RolePermission:
    permission: Permission


@dataclass
class Role:
    role_permissions: list[RolePermission]


@dataclass
class UserRole:
    role: Role
    study_id: UUID | None = None
    site_id: UUID | None = None


@dataclass
class User:
    user_roles: list[UserRole] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    status: str = "active"


class Gateway:
    def __init__(self, mode: str, *, allowed: bool = False, unavailable: bool = False):
        self.mode = mode
        self.allowed = allowed
        self.unavailable = unavailable

    def decide(self, user, permission, *, study_id, site_id):
        if self.unavailable:
            raise ServiceUnavailableError()
        return PlatformDecision(
            allowed=self.allowed,
            decision_id=uuid4(),
            policy_version=4,
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
            reason_code="permission_granted" if self.allowed else "permission_not_granted",
        )


def _local_user(permission: str | None = None) -> User:
    if permission is None:
        return User()
    return User(
        user_roles=[
            UserRole(
                role=Role(role_permissions=[RolePermission(Permission(permission))])
            )
        ]
    )


def test_enforced_mode_uses_central_decision_as_authority() -> None:
    PermissionService(Gateway("enforced", allowed=True)).require(
        _local_user(), "study.read"
    )
    with pytest.raises(AuthorizationError):
        PermissionService(Gateway("enforced", allowed=False)).require(
            _local_user("study.read"), "study.read"
        )


def test_shadow_mode_preserves_local_result_and_tolerates_outage() -> None:
    PermissionService(Gateway("shadow", allowed=False)).require(
        _local_user("study.read"), "study.read"
    )
    PermissionService(Gateway("shadow", unavailable=True)).require(
        _local_user("study.read"), "study.read"
    )
    with pytest.raises(AuthorizationError):
        PermissionService(Gateway("shadow", allowed=True)).require(
            _local_user(), "study.read"
        )


def test_enforced_mode_fails_closed_when_control_plane_is_unavailable() -> None:
    with pytest.raises(ServiceUnavailableError):
        PermissionService(Gateway("enforced", unavailable=True)).require(
            _local_user("study.read"), "study.read"
        )

