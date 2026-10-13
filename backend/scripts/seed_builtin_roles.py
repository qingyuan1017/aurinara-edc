"""Seed built-in roles and synchronize the complete catalog with Platform."""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.permissions import seed_roles_and_permissions
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import Role, RolePermission
from app.services.shared.platform_authorization import (
    PlatformAuthorizationClient,
    namespaced_permission,
)

PLATFORM_ROLE_NAMES = {"System Administrator": "EDC System Administrator"}


async def seed() -> None:
    async with async_session_factory() as session:
        await seed_roles_and_permissions(session)
        await session.commit()

    settings = get_settings()
    can_sync = all(
        (
            settings.platform_control_plane_url,
            settings.platform_service_token_url,
            settings.platform_service_client_id,
            settings.platform_service_client_secret,
        )
    )
    if settings.platform_authorization_mode == "enforced" and not can_sync:
        raise RuntimeError("Enforced Platform authorization requires role-sync credentials")
    if can_sync:
        async with async_session_factory() as session:
            roles = list(
                (
                    await session.scalars(
                        select(Role)
                        .options(
                            selectinload(Role.role_permissions).selectinload(
                                RolePermission.permission
                            )
                        )
                        .order_by(Role.name)
                    )
                ).all()
            )
        catalog = [
            {
                "source_role_id": str(role.id),
                "name": PLATFORM_ROLE_NAMES.get(role.name, role.name),
                "description": role.description,
                "scope_level": str(role.scope_level),
                "permissions": sorted(
                    namespaced_permission(item.permission.code) for item in role.role_permissions
                ),
            }
            for role in roles
        ]
        platform = PlatformAuthorizationClient(settings)
        registered = platform.sync_roles(catalog)
        local_ids = {role.id for role in roles}
        if {item.id for item in registered} != local_ids:
            raise RuntimeError("Platform did not preserve the EDC role IDs")
        async with async_session_factory() as session:
            sites = list(
                (
                    await session.scalars(
                        select(Site)
                        .join(Study, Study.id == Site.study_id)
                        .where(
                            Site.deleted_at.is_(None),
                            Study.platform_managed.is_(True),
                        )
                        .order_by(Site.study_id, Site.name)
                    )
                ).all()
            )
        for site in sites:
            platform.sync_site(
                study_id=site.study_id,
                site_id=site.id,
                name=site.name,
                country=site.country,
                state=site.region,
                city=None,
                status=str(site.status),
            )


if __name__ == "__main__":
    asyncio.run(seed())
