"""Export EDC identities and canonical role IDs for reviewed platform import."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.edc.study import Study
from app.models.shared.identity import Role, RolePermission, User, UserRole
from app.services.shared.platform_authorization import namespaced_permission


def _load_identity_map(path: Path) -> dict[UUID, tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        UUID(user_id): (str(value["issuer"]), str(value["subject"]))
        for user_id, value in payload.items()
    }


def _platform_permissions(role: Role) -> list[str]:
    local = {item.permission.code for item in role.role_permissions}
    result = {namespaced_permission(code) for code in local}
    if "study.create" in local:
        result.add("platform.study.create")
    if "study.read" in local:
        result.add("platform.study.read")
    if "study.configure" in local:
        result.add("platform.study.manage")
    if "user.assign" in local:
        result.update({"platform.membership.read", "platform.membership.manage"})
    if "user.create" in local or "user.update" in local:
        result.add("platform.user.manage")
    return sorted(result)


async def export_snapshot(identity_map_path: Path, output_path: Path) -> None:
    settings = get_settings()
    explicit_identities = _load_identity_map(identity_map_path)
    async with async_session_factory() as session:
        users = list((await session.execute(select(User))).scalars())
        studies = list((await session.execute(select(Study))).scalars())
        roles = list(
            (
                await session.execute(
                    select(Role).options(
                        selectinload(Role.role_permissions).selectinload(RolePermission.permission)
                    )
                )
            ).scalars()
        )
        assignments = list((await session.execute(select(UserRole))).scalars())

    exported_users = []
    for user in users:
        identity = explicit_identities.get(user.id)
        if identity is None and user.external_subject:
            issuer = settings.platform_identity_issuer or settings.auth_issuer
            if not issuer:
                raise ValueError("platform identity issuer is required")
            identity = (issuer, user.external_subject)
        if identity is None:
            raise ValueError(f"user {user.id} has no reviewed OIDC issuer/subject mapping")
        exported_users.append(
            {
                "id": str(user.id),
                "issuer": identity[0],
                "subject": identity[1],
                "email": user.email,
                "display_name": f"{user.first_name} {user.last_name}".strip(),
                "status": str(user.status),
            }
        )

    payload = {
        "schema_version": "1.0.0",
        "users": exported_users,
        "studies": [
            {
                "id": str(study.id),
                "code": study.study_code,
                "display_name": study.title,
                "sponsor": study.sponsor,
                "status": "archived" if str(study.status) == "Archived" else "active",
                "created_by": str(study.created_by),
            }
            for study in studies
        ],
        "roles": [
            {
                "id": str(role.id),
                "product": "aurinara-edc",
                "name": role.name,
                "description": role.description,
                "permissions": _platform_permissions(role),
            }
            for role in roles
        ],
        "assignments": [
            {
                "id": str(item.id),
                "user_id": str(item.user_id),
                "role_id": str(item.role_id),
                "study_id": str(item.study_id) if item.study_id else None,
                "site_id": str(item.site_id) if item.site_id else None,
                "assigned_by": str(item.assigned_by or item.user_id),
            }
            for item in assignments
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-map", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(export_snapshot(args.identity_map, args.output))


if __name__ == "__main__":
    main()
