import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import AuthorizationError, ServiceUnavailableError
from app.core.permissions import ROLE_DEFINITIONS
from app.schemas.shared.permission import CTMS_PERMISSION_ALIASES, PV_PERMISSION_ALIASES
from app.services.shared.permission_service import PermissionService
from app.services.shared.platform_authorization import (
    PlatformAuthorizationClient,
    PlatformDecision,
    namespaced_permission,
)


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


@pytest.mark.parametrize("alias,canonical", CTMS_PERMISSION_ALIASES.items())
def test_ctms_permission_aliases_match_registered_platform_actions(
    alias: str, canonical: str
) -> None:
    assert namespaced_permission(alias) == canonical
    assert namespaced_permission(f"ctms.{alias}") == canonical
    assert namespaced_permission(canonical) == canonical


@pytest.mark.parametrize("alias,canonical", PV_PERMISSION_ALIASES.items())
def test_pv_permission_aliases_match_registered_platform_actions(
    alias: str, canonical: str
) -> None:
    expected = f"edc.{canonical}"
    assert namespaced_permission(alias) == expected
    assert namespaced_permission(f"pv.{alias}") == expected
    assert namespaced_permission(canonical) == expected


def test_every_supported_alias_is_granted_by_a_builtin_role() -> None:
    builtin_permissions = {
        permission
        for definition in ROLE_DEFINITIONS.values()
        for permission in definition["permissions"]
    }
    assert set(CTMS_PERMISSION_ALIASES.values()) <= builtin_permissions
    assert set(PV_PERMISSION_ALIASES.values()) <= builtin_permissions


def test_authorization_request_normalizes_route_permission_before_platform_decision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/authorization/decisions"
        assert json.loads(request.content)["action"] == "ctms.operational_data_read"
        return httpx.Response(
            200,
            json={
                "allowed": True,
                "decision_id": str(uuid4()),
                "policy_version": 5,
                "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                "reason_code": "permission_granted",
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

    decision = client.decide(
        _local_user(),
        "ctms.operational-data-read",
        study_id=uuid4(),
        site_id=None,
    )

    assert decision.allowed is True


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


def test_role_catalog_registration_returns_platform_mappings() -> None:
    source_role_id = uuid4()
    platform_role_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/v1/products/aurinara-edc/roles"
        assert request.headers["Authorization"] == "Bearer service-token"
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(platform_role_id),
                    "source_role_id": str(source_role_id),
                    "product": "aurinara-edc",
                    "name": "Data Manager",
                    "description": "Study data management",
                    "scope_level": "study",
                    "assignable": True,
                    "status": "active",
                }
            ],
        )

    settings = Settings(
        _env_file=None,
        environment="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))

    registered = client.sync_roles(
        [
            {
                "source_role_id": str(source_role_id),
                "name": "Data Manager",
                "description": "Study data management",
                "scope_level": "study",
                "permissions": ["edc.query.create"],
            }
        ]
    )

    assert registered[0].id == platform_role_id
    assert registered[0].source_role_id == source_role_id
    assert registered[0].scope_level == "study"


def test_permission_catalog_registration_does_not_define_roles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/v1/products/aurinara-edc/permissions"
        payload = json.loads(request.content)
        assert payload == {
            "permissions": [
                {
                    "code": "edc.designer.odm.export",
                    "description": "Export ODM metadata",
                    "module": "designer",
                    "allowed_scope_levels": ["system", "study"],
                }
            ]
        }
        return httpx.Response(200, json=[{"code": "edc.designer.odm.export"}])

    settings = Settings(
        _env_file=None,
        environment="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))

    registered = client.sync_permissions(
        [
            {
                "code": "edc.designer.odm.export",
                "description": "Export ODM metadata",
                "module": "designer",
                "allowed_scope_levels": ["system", "study"],
            }
        ]
    )

    assert registered == ("edc.designer.odm.export",)


def test_study_creator_role_bundle_is_stable_and_study_scoped() -> None:
    from app.core.permissions import (
        PLATFORM_MANAGED_ROLE_IDS,
        PLATFORM_STUDY_CREATOR_ROLE_NAMES,
        permission_catalog,
        platform_role_catalog,
    )

    catalog = {str(item["name"]): item for item in platform_role_catalog()}
    permission_scopes = {
        namespaced_permission(str(item["code"])): set(item["allowed_scope_levels"])
        for item in permission_catalog()
    }

    assert set(PLATFORM_STUDY_CREATOR_ROLE_NAMES) <= set(catalog)
    for name in PLATFORM_STUDY_CREATOR_ROLE_NAMES:
        assert catalog[name]["source_role_id"] == str(PLATFORM_MANAGED_ROLE_IDS[name])
        assert catalog[name]["scope_level"] == "study"
        assert catalog[name]["permissions"]
        assert set(map(str, catalog[name]["permissions"])) <= permission_scopes.keys()
        assert all(
            catalog[name]["scope_level"] in permission_scopes[str(code)]
            for code in catalog[name]["permissions"]
        )
    assert all(
        str(code).startswith("ctms.")
        for code in catalog["CTMS_Operations_User"]["permissions"]
    )


def test_ctms_site_registration_preserves_the_generated_canonical_id() -> None:
    study_id = uuid4()
    site_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == (f"/v1/products/aurinara-edc/studies/{study_id}/sites/{site_id}")
        assert request.headers["Authorization"] == "Bearer service-token"
        assert json.loads(request.content) == {
            "name": "General Hospital",
            "country": "US",
            "state": "New York",
            "city": "New York",
            "status": "active",
        }
        return httpx.Response(
            200,
            json={
                "id": str(site_id),
                "study_id": str(study_id),
                "name": "General Hospital",
            },
        )

    settings = Settings(
        _env_file=None,
        environment="test",
        platform_control_plane_url="https://platform.test",
        platform_authorization_mode="enforced",
        platform_service_token_url="https://issuer.test/token",
        platform_service_client_id="client",
        platform_service_client_secret="secret",
    )
    client = PlatformAuthorizationClient(settings, httpx.MockTransport(handler))
    client._token = ("service-token", float("inf"))

    client.sync_site(
        study_id=study_id,
        site_id=site_id,
        name="General Hospital",
        country="US",
        state="New York",
        city="New York",
    )
