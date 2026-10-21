"""Idempotent canonical study projection from the platform event stream."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.permissions import PERMISSION_CODES, platform_permission_code
from app.models.edc.study import Study, StudyStatus
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.shared.platform_projection import (
    PlatformMembershipProjection,
    PlatformProjectionEvent,
)


@dataclass(frozen=True, slots=True)
class PlatformEvent:
    id: UUID
    type: str
    aggregate_id: UUID
    sequence: int
    data: dict[str, object]

    @classmethod
    def parse(cls, payload: dict[str, object]) -> "PlatformEvent":
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("platform event data must be an object")
        return cls(
            id=UUID(str(payload["id"])),
            type=str(payload["type"]),
            aggregate_id=UUID(str(payload["aggregate_id"])),
            sequence=int(payload["sequence"]),
            data=data,
        )


async def apply_platform_event(session: AsyncSession, event: PlatformEvent) -> bool:
    """Apply a study event once without changing EDC-owned clinical lifecycle state."""

    if await session.get(PlatformProjectionEvent, event.id) is not None:
        return False
    if event.type in {"platform.user.created.v1", "platform.user.updated.v1"}:
        return await _apply_user_event(session, event)
    if event.type == "platform.role.changed.v1":
        return await _apply_role_event(session, event)
    if event.type == "platform.membership.changed.v1":
        return await _apply_membership_event(session, event)
    if event.type == "platform.assignment.changed.v1":
        if event.data.get("product") not in {"platform", "aurinara-edc"}:
            return False
        return await _apply_system_assignment_event(session, event)
    if event.type not in {"platform.study.created.v1", "platform.study.updated.v1"}:
        return False
    study = await session.get(Study, event.aggregate_id)
    code = str(event.data["code"])
    if study is None:
        collision_result = await session.execute(select(Study).where(Study.study_code == code))
        if collision_result.scalars().first() is not None:
            raise ConflictError(
                message="Canonical study identity conflicts with an existing study",
                details={"reason": "STUDY_IDENTITY_CONFLICT", "study_code": code},
            )
        # The shared event establishes identity only. EDC clinical configuration,
        # status transitions, and StudyVersion creation remain EDC-owned actions.
        created_by = await _resolve_local_user_id(session, UUID(str(event.data["created_by"])))
        study = Study(
            id=event.aggregate_id,
            study_code=code,
            title=str(event.data["display_name"]),
            sponsor=(str(event.data["sponsor"]) if event.data.get("sponsor") else None),
            status=StudyStatus.draft,
            created_by=created_by,
            platform_managed=True,
            platform_revision=event.sequence,
            platform_registry_status=str(event.data["status"]),
        )
        session.add(study)
    elif study.platform_revision is None or event.sequence > study.platform_revision:
        if study.study_code != code:
            raise ConflictError(
                message="Canonical study code does not match the local identity",
                details={"reason": "STUDY_IDENTITY_CONFLICT", "study_code": code},
            )
        study.title = str(event.data["display_name"])
        if "sponsor" in event.data:
            study.sponsor = str(event.data["sponsor"]) if event.data["sponsor"] else None
        study.platform_managed = True
        study.platform_revision = event.sequence
        study.platform_registry_status = str(event.data["status"])
    session.add(
        PlatformProjectionEvent(
            id=event.id,
            event_type=event.type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
        )
    )
    await session.flush()
    return True


_PLATFORM_TO_LOCAL_PERMISSION = {
    platform_permission_code(local_code): local_code for local_code in PERMISSION_CODES
}


def _local_permission_code(code: str) -> str | None:
    return _PLATFORM_TO_LOCAL_PERMISSION.get(code)


async def _apply_role_event(session: AsyncSession, event: PlatformEvent) -> bool:
    """Project Platform-owned role composition for local scoped filtering."""

    if event.data.get("product") not in {"aurinara-edc", "platform"}:
        return False
    role_id = UUID(
        str(event.data.get("source_role_id") or event.data.get("role_id") or event.aggregate_id)
    )
    name = str(event.data["name"])
    local_codes = {
        local_code
        for code in event.data.get("permission_codes", [])
        if (local_code := _local_permission_code(str(code))) is not None
    }
    unsupported = local_codes - PERMISSION_CODES
    if unsupported:
        raise ConflictError(
            message="Platform role references an unregistered EDC permission",
            details={
                "reason": "PERMISSION_NOT_REGISTERED",
                "permission_codes": sorted(unsupported),
            },
        )
    role = await session.get(Role, role_id)
    if (
        role is not None
        and role.platform_revision is not None
        and event.sequence <= role.platform_revision
    ):
        session.add(
            PlatformProjectionEvent(
                id=event.id,
                event_type=event.type,
                aggregate_id=event.aggregate_id,
                sequence=event.sequence,
            )
        )
        await session.flush()
        return True
    collision = await session.scalar(select(Role).where(Role.name == name, Role.id != role_id))
    if collision is not None:
        raise ConflictError(
            message="Platform role identity conflicts with an existing EDC role",
            details={"reason": "ROLE_IDENTITY_CONFLICT"},
        )
    if role is None:
        role = Role(
            id=role_id,
            name=name,
            scope_level=str(event.data["scope_level"]),
            description=(str(event.data["description"]) if event.data.get("description") else None),
            is_system=False,
            platform_managed=True,
            platform_revision=event.sequence,
            platform_status=str(event.data["status"]),
        )
        session.add(role)
        await session.flush()
    else:
        role.name = name
        role.scope_level = str(event.data["scope_level"])
        role.description = str(event.data["description"]) if event.data.get("description") else None
        role.platform_managed = True
        role.platform_revision = event.sequence
        role.platform_status = str(event.data["status"])

    permissions_by_code: dict[str, Permission] = {}
    if local_codes:
        existing = await session.execute(select(Permission).where(Permission.code.in_(local_codes)))
        permissions_by_code = {item.code: item for item in existing.scalars().all()}
    for code in sorted(local_codes - permissions_by_code.keys()):
        permission = Permission(code=code, description=code.replace("_", " ").replace(".", " · "))
        session.add(permission)
        permissions_by_code[code] = permission
    await session.flush()
    permission_ids = {item.id for item in permissions_by_code.values()}
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    session.add_all(
        RolePermission(role_id=role.id, permission_id=permission_id)
        for permission_id in permission_ids
    )
    session.add(
        PlatformProjectionEvent(
            id=event.id,
            event_type=event.type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
        )
    )
    await session.flush()
    return True


async def _apply_user_event(session: AsyncSession, event: PlatformEvent) -> bool:
    user = await session.get(User, event.aggregate_id)
    email = str(event.data["email"])
    issuer = str(event.data["issuer"])
    subject = str(event.data["subject"])
    first_name, last_name = _split_display_name(str(event.data["display_name"]))
    if user is None:
        collision_result = await session.execute(select(User).where(User.email == email))
        if collision_result.scalars().first() is not None:
            raise ConflictError(
                message="Canonical user identity conflicts with an existing user",
                details={"reason": "USER_IDENTITY_CONFLICT"},
            )
        user = User(
            id=event.aggregate_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            status=_user_status(str(event.data["status"])),
            password_hash=None,
            external_identity_provider="oidc",
            external_issuer=issuer,
            external_subject=subject,
            platform_managed=True,
            platform_revision=event.sequence,
        )
        session.add(user)
    elif user.platform_revision is None or event.sequence > user.platform_revision:
        if user.external_issuer is not None and (user.external_issuer, user.external_subject) != (
            issuer,
            subject,
        ):
            raise ConflictError(
                message="Canonical user subject does not match the local identity",
                details={"reason": "USER_IDENTITY_CONFLICT"},
            )
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.status = _user_status(str(event.data["status"]))
        user.external_identity_provider = user.external_identity_provider or "oidc"
        user.external_issuer = issuer
        user.external_subject = subject
        user.platform_managed = True
        user.platform_revision = event.sequence
    session.add(
        PlatformProjectionEvent(
            id=event.id,
            event_type=event.type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
        )
    )
    await session.flush()
    return True


def _split_display_name(value: str) -> tuple[str, str]:
    parts = value.strip().split(maxsplit=1)
    first = (parts[0] if parts else "Unknown")[:150]
    last = (parts[1] if len(parts) == 2 else "Unknown")[:150]
    return first, last


def _user_status(value: str) -> UserStatus:
    return UserStatus.inactive if value == "inactive" else UserStatus.active


async def _apply_membership_event(session: AsyncSession, event: PlatformEvent) -> bool:
    if event.data.get("product") not in {None, "platform", "aurinara-edc"}:
        return False
    study_id = UUID(str(event.data["study_id"]))
    user_id = UUID(str(event.data["user_id"]))
    raw_site_id = event.data.get("site_id")
    site_id = UUID(str(raw_site_id)) if raw_site_id else None
    scope_key = f"{study_id}:{user_id}:{site_id or '*'}"
    cursor = await session.get(PlatformMembershipProjection, scope_key)
    if cursor is not None and event.sequence <= cursor.sequence:
        session.add(
            PlatformProjectionEvent(
                id=event.id,
                event_type=event.type,
                aggregate_id=event.aggregate_id,
                sequence=event.sequence,
            )
        )
        await session.flush()
        return True
    role_ids = [UUID(str(value)) for value in event.data.get("role_ids", [])]
    await _validate_role_ids(session, role_ids)
    await session.execute(
        delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.study_id == study_id,
            UserRole.site_id == site_id,
            UserRole.platform_managed.is_(True),
        )
    )
    assigned_by_raw = event.data.get("assigned_by")
    assigned_by = UUID(str(assigned_by_raw)) if assigned_by_raw else None
    session.add_all(
        [
            UserRole(
                user_id=user_id,
                role_id=role_id,
                study_id=study_id,
                site_id=site_id,
                assigned_by=assigned_by,
                platform_managed=True,
                platform_role_id=role_id,
            )
            for role_id in role_ids
        ]
    )
    if cursor is None:
        cursor = PlatformMembershipProjection(
            scope_key=scope_key,
            study_id=study_id,
            user_id=user_id,
            site_id=site_id,
            sequence=event.sequence,
        )
        session.add(cursor)
    else:
        cursor.sequence = event.sequence
    session.add(
        PlatformProjectionEvent(
            id=event.id,
            event_type=event.type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
        )
    )
    await session.flush()
    return True


async def _apply_system_assignment_event(session: AsyncSession, event: PlatformEvent) -> bool:
    platform_user_id = UUID(str(event.data["user_id"]))
    issuer = str(event.data.get("issuer") or "")
    subject = str(event.data.get("subject") or "")
    user = await session.get(User, platform_user_id)
    if user is None and issuer and subject:
        user = await session.scalar(
            select(User).where(
                User.external_issuer == issuer,
                User.external_subject == subject,
            )
        )
    if user is None:
        raise ConflictError(
            message="Platform assignment references an unknown local user",
            details={"reason": "USER_PROJECTION_REQUIRED"},
        )
    scope_key = f"system:{platform_user_id}"
    cursor = await session.get(PlatformMembershipProjection, scope_key)
    if cursor is not None and event.sequence <= cursor.sequence:
        session.add(
            PlatformProjectionEvent(
                id=event.id,
                event_type=event.type,
                aggregate_id=event.aggregate_id,
                sequence=event.sequence,
            )
        )
        await session.flush()
        return True
    role_ids = [UUID(str(value)) for value in event.data.get("role_ids", [])]
    await _validate_role_ids(session, role_ids)
    await session.execute(
        delete(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.study_id.is_(None),
            UserRole.site_id.is_(None),
            UserRole.platform_managed.is_(True),
        )
    )
    assigned_by_raw = event.data.get("assigned_by")
    assigned_by = UUID(str(assigned_by_raw)) if assigned_by_raw else None
    if assigned_by is not None and await session.get(User, assigned_by) is None:
        assigned_by = user.id if assigned_by_raw == str(platform_user_id) else None
    session.add_all(
        [
            UserRole(
                user_id=user.id,
                role_id=role_id,
                study_id=None,
                site_id=None,
                assigned_by=assigned_by,
                platform_managed=True,
                platform_role_id=role_id,
            )
            for role_id in role_ids
        ]
    )
    if cursor is None:
        session.add(
            PlatformMembershipProjection(
                scope_key=scope_key,
                study_id=None,
                user_id=user.id,
                site_id=None,
                sequence=event.sequence,
            )
        )
    else:
        cursor.sequence = event.sequence
    session.add(
        PlatformProjectionEvent(
            id=event.id,
            event_type=event.type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
        )
    )
    await session.flush()
    return True


async def _validate_role_ids(session: AsyncSession, role_ids: list[UUID]) -> None:
    if not role_ids:
        return
    local_roles_result = await session.execute(select(Role.id).where(Role.id.in_(role_ids)))
    if set(local_roles_result.scalars()) != set(role_ids):
        raise ConflictError(
            message="Platform assignment references a missing EDC role",
            details={"reason": "ROLE_NOT_REGISTERED"},
        )


async def _resolve_local_user_id(session: AsyncSession, platform_user_id: UUID) -> UUID:
    if await session.get(User, platform_user_id) is not None:
        return platform_user_id
    cursor = await session.get(PlatformMembershipProjection, f"system:{platform_user_id}")
    if cursor is not None and await session.get(User, cursor.user_id) is not None:
        return cursor.user_id
    raise ConflictError(
        message="Platform event references an unknown local user",
        details={"reason": "USER_PROJECTION_REQUIRED"},
    )
