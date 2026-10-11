from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import AuthorizationError, ServiceUnavailableError
from app.services.shared.permission_service import PermissionService
from app.services.shared.platform_authorization import PlatformAuthorizationClient, PlatformDecision


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
    external_subject: str | None = "subject"
    external_issuer: str | None = "https://issuer.test"


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
        user_roles=[UserRole(role=Role(role_permissions=[RolePermission(Permission(permission))]))]
    )


def test_enforced_mode_uses_central_decision_as_authority() -> None:
    PermissionService(Gateway("enforced", allowed=True)).require(_local_user(), "study.read")
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
        PermissionService(Gateway("shadow", allowed=True)).require(_local_user(), "study.read")


def test_enforced_mode_fails_closed_when_control_plane_is_unavailable() -> None:
    with pytest.raises(ServiceUnavailableError):
        PermissionService(Gateway("enforced", unavailable=True)).require(
            _local_user("study.read"), "study.read"
        )


def test_service_token_requests_cognito_scope_and_resource() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        command = dict(httpx.QueryParams(request.content.decode()))
        assert command["grant_type"] == "client_credentials"
        assert command["scope"] == "https://aurinara-platform.local/service"
        assert command["resource"] == "https://aurinara-platform.local"
        return httpx.Response(200, json={"access_token": "token", "expires_in": 300})

    settings = Settings(
        _env_file=None,
        environment="test",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))

    assert client.service_token() == "token"


def test_batch_authorization_uses_one_control_plane_request() -> None:
    study_ids = (uuid4(), uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/authorization/decisions:batch"
        return httpx.Response(
            200,
            json={
                "decisions": [
                    {
                        "allowed": allowed,
                        "decision_id": str(uuid4()),
                        "policy_version": 5,
                        "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                        "reason_code": (
                            "permission_granted" if allowed else "permission_not_granted"
                        ),
                    }
                    for allowed in (True, False)
                ]
            },
        )

    settings = Settings(
        _env_file=None,
        environment="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_identity_issuer="https://issuer.test",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))

    decisions = client.decide_batch(
        _local_user(),
        "study.read",
        tuple((study_id, None) for study_id in study_ids),
    )

    assert [decision.allowed for decision in decisions] == [True, False]
