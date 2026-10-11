"""Create a reviewed platform-role to EDC-role mapping.

Run from ``backend/`` after applying migrations::

    python -m scripts.map_platform_role PLATFORM_ROLE_UUID LOCAL_ROLE_UUID

The command is idempotent and refuses to silently remap a platform role.  A
different mapping must be reviewed and removed explicitly before replacement.
"""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.shared.identity import Role
from app.models.shared.platform_projection import PlatformRoleMapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform_role_id", type=UUID)
    parser.add_argument("local_role_id", type=UUID)
    return parser.parse_args()


async def map_role(platform_role_id: UUID, local_role_id: UUID) -> None:
    async with async_session_factory() as session:
        role = await session.get(Role, local_role_id)
        if role is None:
            raise SystemExit(f"Local role {local_role_id} does not exist")

        existing = await session.scalar(
            select(PlatformRoleMapping).where(
                PlatformRoleMapping.platform_role_id == platform_role_id
            )
        )
        if existing is not None:
            if existing.local_role_id != local_role_id:
                raise SystemExit(
                    "Platform role is already mapped to "
                    f"{existing.local_role_id}; refusing an implicit remap"
                )
            print(  # noqa: T201 - command-line administrator feedback
                f"Mapping already exists: {platform_role_id} -> {role.name}"
            )
            return

        session.add(
            PlatformRoleMapping(
                platform_role_id=platform_role_id,
                local_role_id=local_role_id,
            )
        )
        await session.commit()
        print(  # noqa: T201 - command-line administrator feedback
            f"Mapped platform role {platform_role_id} -> {role.name} ({local_role_id})"
        )


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(map_role(arguments.platform_role_id, arguments.local_role_id))
