"""Seed standalone roles or register EDC capabilities with Platform."""

import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.permissions import (
    permission_catalog,
    seed_permission_catalog,
    seed_roles_and_permissions,
)
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.services.shared.platform_authorization import (
    PlatformAuthorizationClient,
    namespaced_permission,
)


async def seed() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        if settings.platform_authorization_mode == "disabled":
            # Standalone development has no Platform from which to project roles.
            await seed_roles_and_permissions(session)
        else:
            await seed_permission_catalog(session)
        await session.commit()

    can_sync = all(
        (
            settings.platform_control_plane_url,
            settings.platform_service_token_url,
            settings.platform_service_client_id,
            settings.platform_service_client_secret,
        )
    )
    if settings.platform_authorization_mode == "enforced" and not can_sync:
        raise RuntimeError("Enforced Platform authorization requires permission-sync credentials")
    if can_sync:
        catalog = [
            {
                **definition,
                "code": namespaced_permission(str(definition["code"])),
            }
            for definition in permission_catalog()
        ]
        platform = PlatformAuthorizationClient(settings)
        registered = platform.sync_permissions(catalog)
        if set(registered) != {str(item["code"]) for item in catalog}:
            raise RuntimeError("Platform did not preserve the EDC permission catalog")
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
