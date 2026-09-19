"""Property tests for the shared CTMS authorization boundary.

**Validates: Requirements 2.1-2.3, 2.7, 2.10-2.11, 3.9, 4.10, 5.15,
6.8, 6.12, 7.8, 7.10, 8.6-8.7, 10.1-10.18, 13.6, 14.5**

Property 3: Authorization is exact and module-wide.

The boundary fake deliberately keeps CTMS-owned and EDC-owned state in separate
collections.  It exercises the real PermissionService without a database or
external services and checks that denied commands are side-effect free across all
collections, not only the collection associated with the attempted command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.models.identity import UserStatus
from app.schemas.permission import normalize_permission_code
from app.services.permission_service import PermissionService


class Scope(StrEnum):
    """Role assignment scopes generated for the property."""

    SYSTEM = "system"
    STUDY = "study"
    SITE = "site"


@dataclass(frozen=True)
class FakePermission:
    code: str


@dataclass(frozen=True)
class FakeRolePermission:
    permission: FakePermission


@dataclass(frozen=True)
class FakeRole:
    name: str
    scope_level: str
    role_permissions: list[FakeRolePermission]


@dataclass(frozen=True)
class FakeUserRole:
    role: FakeRole
    study_id: UUID | None
    site_id: UUID | None


@dataclass
class FakeUser:
    user_roles: list[FakeUserRole]
    status: UserStatus = UserStatus.active
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class TargetRecord:
    """A CTMS operational target; EDC identifiers are never writable here."""

    study_id: UUID
    site_id: UUID


@dataclass(frozen=True)
class ModuleOperation:
    name: str
    permission: str
    state_bucket: str | None


@dataclass
class InMemoryModuleState:
    """Deterministic state for all module boundaries exercised by this property."""

    ctms: list[str] = field(default_factory=list)
    projections: list[str] = field(default_factory=list)
    coordination: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    edc: list[str] = field(default_factory=list)

    def snapshot(self) -> tuple[tuple[str, ...], ...]:
        return (
            tuple(self.ctms),
            tuple(self.projections),
            tuple(self.coordination),
            tuple(self.attachments),
            tuple(self.edc),
        )


# These are the shared permission codes exposed by the CTMS role definitions,
# plus the shared upload permission used by operational attachments.
PERMISSIONS: Final[tuple[str, ...]] = (
    "ctms.operational_data_read",
    "ctms.operational_study_management",
    "ctms.operational_site_management",
    "ctms.monitoring_activity_management",
    "ctms.enrollment_management",
    "ctms.conflict_management",
    "ctms.coordination_replay",
    "file.upload",
)

OPERATIONS: Final[tuple[ModuleOperation, ...]] = (
    ModuleOperation(
        "study-management",
        "ctms.operational_study_management",
        "ctms",
    ),
    ModuleOperation(
        "site-management",
        "ctms.operational_site_management",
        "ctms",
    ),
    ModuleOperation(
        "enrollment-management",
        "ctms.enrollment_management",
        "ctms",
    ),
    ModuleOperation(
        "monitoring-management",
        "ctms.monitoring_activity_management",
        "ctms",
    ),
    # Reading a minimized projection is intentionally side-effect free.
    ModuleOperation(
        "projection-read",
        "ctms.operational_data_read",
        None,
    ),
    ModuleOperation(
        "conflict-management",
        "ctms.conflict_management",
        "coordination",
    ),
    ModuleOperation(
        "coordination-replay",
        "ctms.coordination_replay",
        "coordination",
    ),
    ModuleOperation("operational-attachment-upload", "file.upload", "attachments"),
)


def _uuid_list() -> st.SearchStrategy[list[UUID]]:
    return st.lists(st.uuids(), min_size=1, max_size=4, unique=True)


@st.composite
def authorization_case(draw: st.DrawFn) -> dict[str, object]:
    """Generate role grants, a scoped target, and one CTMS operation."""

    studies = draw(_uuid_list())
    sites = draw(_uuid_list())
    target = TargetRecord(
        study_id=draw(st.sampled_from(studies)),
        site_id=draw(st.sampled_from(sites)),
    )

    assignments: list[FakeUserRole] = []
    for index in range(draw(st.integers(min_value=0, max_value=5))):
        scope = draw(st.sampled_from(list(Scope)))
        permissions = draw(
            st.lists(
                st.sampled_from(PERMISSIONS), min_size=1, max_size=len(PERMISSIONS), unique=True
            )
        )
        if scope is Scope.SYSTEM:
            study_id = site_id = None
        elif scope is Scope.STUDY:
            study_id = draw(st.sampled_from(studies))
            site_id = None
        else:
            study_id = draw(st.sampled_from(studies))
            site_id = draw(st.sampled_from(sites))

        role = FakeRole(
            name=f"generated-role-{index}",
            scope_level=scope.value,
            role_permissions=[FakeRolePermission(FakePermission(code)) for code in permissions],
        )
        assignments.append(FakeUserRole(role, study_id, site_id))

    return {
        "target": target,
        "assignments": assignments,
        "operation": draw(st.sampled_from(OPERATIONS)),
        "active": draw(st.booleans()),
    }


def _grant_covers(
    assignment: FakeUserRole,
    permission: str,
    target: TargetRecord,
) -> bool:
    """Compute expected authorization independently of PermissionService."""

    permission = normalize_permission_code(permission)
    has_code = any(
        normalize_permission_code(role_permission.permission.code) == permission
        for role_permission in assignment.role.role_permissions
    )
    if not has_code:
        return False
    if assignment.study_id is None and assignment.site_id is None:
        return True
    if assignment.site_id is None:
        return assignment.study_id == target.study_id
    return (
        assignment.study_id == target.study_id and assignment.site_id == target.site_id
    )


def _expected_authorization(case: dict[str, object]) -> bool:
    """Return the policy decision expected from generated raw grants."""

    if not case["active"]:
        return False
    target = case["target"]
    operation = case["operation"]
    assert isinstance(target, TargetRecord)
    assert isinstance(operation, ModuleOperation)
    return any(
        _grant_covers(assignment, operation.permission, target)
        for assignment in case["assignments"]
    )


def _build_user(case: dict[str, object]) -> FakeUser:
    return FakeUser(
        user_roles=case["assignments"],
        status=UserStatus.active if case["active"] else UserStatus.inactive,
    )


def _execute(
    service: PermissionService,
    state: InMemoryModuleState,
    user: FakeUser,
    target: TargetRecord,
    operation: ModuleOperation,
) -> bool:
    """Apply one guarded operation, returning whether authorization succeeded."""

    try:
        service.require(
            user,
            operation.permission,
            study_id=target.study_id,
            site_id=target.site_id,
        )
    except (AuthenticationError, AuthorizationError):
        return False

    if operation.state_bucket is not None:
        bucket = getattr(state, operation.state_bucket)
        bucket.append(f"{operation.name}:{target.study_id}:{target.site_id}")
    return True


class TestCTMSAuthorizationBoundary:
    """Property 3: one shared scope governs every CTMS boundary."""

    @settings(max_examples=150, deadline=None)
    @given(case=authorization_case())
    def test_authorization_is_exact_and_denials_are_module_wide(self, case):
        """Authorization follows grants exactly and denied commands are atomic.

        **Validates: Requirements 2.1-2.3, 2.7, 2.10-2.11, 3.9, 4.10, 5.15,
        6.8, 6.12, 7.8, 7.10, 8.6-8.7, 10.1-10.18, 13.6, 14.5**
        """

        target = case["target"]
        operation = case["operation"]
        assert isinstance(target, TargetRecord)
        assert isinstance(operation, ModuleOperation)

        state = InMemoryModuleState(
            ctms=["existing-ctms-record"],
            projections=["existing-projection"],
            coordination=["existing-coordination-event"],
            attachments=["existing-operational-attachment"],
            edc=["canonical-edc-study-version", "canonical-edc-subject"],
        )
        before = state.snapshot()
        allowed = _expected_authorization(case)
        succeeded = _execute(
            PermissionService(), state, _build_user(case), target, operation
        )

        assert succeeded is allowed
        if not allowed:
            assert state.snapshot() == before
        else:
            # EDC remains authoritative even when a CTMS operation is allowed.
            assert state.edc == list(before[4])
            if operation.state_bucket is None:
                assert state.snapshot() == before
            else:
                # Only the operation's owning collection may receive a side effect.
                for bucket_name, original in zip(
                    ("ctms", "projections", "coordination", "attachments", "edc"),
                    before,
                    strict=True,
                ):
                    bucket = getattr(state, bucket_name)
                    if bucket_name == operation.state_bucket:
                        assert bucket[:-1] == list(original)
                        assert len(bucket) == len(original) + 1
                    else:
                        assert bucket == list(original)
