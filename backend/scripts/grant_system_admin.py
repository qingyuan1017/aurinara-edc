"""Grant an existing user the System Administrator role at system scope.

Run from the backend directory:
    python -m scripts.grant_system_admin jason.zhang@edetek.com

Idempotent: seeds roles/permissions if missing, then assigns the system-scoped
System Administrator role to the named user if not already assigned. Does not
create the user — the user must already exist (e.g. via Cognito JIT provisioning).
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.permissions import seed_roles_and_permissions
from app.models.shared.identity import Role, User, UserRole

ADMIN_ROLE_NAME = "System Administrator"


async def main(email: str) -> None:
    async with async_session_factory() as session:
        # Ensure built-in roles/permissions exist (idempotent).
        await seed_roles_and_permissions(session)
        await session.flush()

        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalars().first()
        if user is None:
            print(f"User not found: {email}. Sign in once so the account is provisioned.")
            return

        role = (
            await session.execute(select(Role).where(Role.name == ADMIN_ROLE_NAME))
        ).scalars().first()
        if role is None:
            print(f"Role '{ADMIN_ROLE_NAME}' not found. Run migrations first.")
            return

        existing = (
            await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id,
                    UserRole.study_id.is_(None),
                    UserRole.site_id.is_(None),
                )
            )
        ).scalars().first()

        if existing is not None:
            print(f"User {email} already has the {ADMIN_ROLE_NAME} role (system scope).")
            await session.commit()
            return

        session.add(
            UserRole(user_id=user.id, role_id=role.id, study_id=None, site_id=None)
        )
        await session.commit()
        print(f"Granted {ADMIN_ROLE_NAME} (system scope) to {email} (user id {user.id}).")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "jason.zhang@edetek.com"
    asyncio.run(main(target))
