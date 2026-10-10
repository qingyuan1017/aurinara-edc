"""Idempotent canonical study projection from the platform event stream."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.edc.study import Study, StudyStatus
from app.models.shared.identity import Role, User, UserRole, UserStatus
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
    if event.type == "platform.membership.changed.v1":
        return await _apply_membership_event(session, event)
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
        study = Study(
            id=event.aggregate_id,
            study_code=code,
            title=str(event.data["display_name"]),
            status=StudyStatus.draft,
            created_by=UUID(str(event.data["created_by"])),
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


async def _apply_user_event(session: AsyncSession, event: PlatformEvent) -> bool:
    user = await session.get(User, event.aggregate_id)
    email = str(event.data["email"])
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
            external_subject=subject,
            platform_managed=True,
            platform_revision=event.sequence,
        )
        session.add(user)
    elif user.platform_revision is None or event.sequence > user.platform_revision:
        if user.external_subject is not None and user.external_subject != subject:
            raise ConflictError(
                message="Canonical user subject does not match the local identity",
                details={"reason": "USER_IDENTITY_CONFLICT"},
            )
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.status = _user_status(str(event.data["status"]))
        user.external_identity_provider = user.external_identity_provider or "oidc"
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
    if role_ids:
        roles_result = await session.execute(select(Role).where(Role.id.in_(role_ids)))
        roles = {role.id for role in roles_result.scalars()}
        missing = set(role_ids) - roles
        if missing:
            raise ConflictError(
                message="Platform membership references an unmapped role",
                details={"reason": "ROLE_MAPPING_REQUIRED"},
            )
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
