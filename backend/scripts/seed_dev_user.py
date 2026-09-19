"""Seed a development user with System Administrator privileges.

Run from the backend directory:
    python -m scripts.seed_dev_user

Creates:
  Email:    admin@edc.local
  Password: Admin123!
  Role:     System Administrator (full access)

Requires a running PostgreSQL database with migrations applied.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.permissions import seed_roles_and_permissions
from app.core.security import hash_password
from app.models.identity import (
    Role,
    User,
    UserRole,
    UserStatus,
)

DEV_USER_EMAIL = "admin@edc-dev.example.com"
DEV_USER_PASSWORD = "Admin123!"
DEV_USER_FIRST = "Dev"
DEV_USER_LAST = "Admin"
DEV_ROLE_NAME = "System Administrator"


async def main() -> None:
    async with async_session_factory() as session:
        # Seed roles and permissions first (idempotent)
        await seed_roles_and_permissions(session)
        await session.flush()

        # Check if user already exists
        result = await session.execute(
            select(User).where(User.email == DEV_USER_EMAIL)
        )
        existing = result.scalars().first()
        if existing:
            # Repair the role assignment for an existing development user.
            # This keeps the seeder useful after role definitions gain new
            # permissions or an earlier seed stopped before assignment.
            role_result = await session.execute(
                select(Role).where(Role.name == DEV_ROLE_NAME)
            )
            role = role_result.scalars().first()
            if role is None:
                print(f"✗ Role '{DEV_ROLE_NAME}' not found. Run migrations first.")
                return

            assignment_result = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == existing.id,
                    UserRole.role_id == role.id,
                    UserRole.study_id.is_(None),
                    UserRole.site_id.is_(None),
                )
            )
            if assignment_result.scalars().first() is None:
                session.add(
                    UserRole(
                        user_id=existing.id,
                        role_id=role.id,
                        study_id=None,
                        site_id=None,
                    )
                )
                await session.flush()
                print(f"✓ Assigned {DEV_ROLE_NAME} role to existing user")

            print(f"✓ Dev user already exists: {DEV_USER_EMAIL}")
            await session.commit()
            return

        # Create the user
        user = User(
            id=uuid.uuid4(),
            email=DEV_USER_EMAIL,
            password_hash=hash_password(DEV_USER_PASSWORD),
            first_name=DEV_USER_FIRST,
            last_name=DEV_USER_LAST,
            status=UserStatus.active,
            mfa_enabled=False,
            last_activity=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()

        # Find the System Administrator role
        role_result = await session.execute(
            select(Role).where(Role.name == DEV_ROLE_NAME)
        )
        role = role_result.scalars().first()
        if role is None:
            print(f"✗ Role '{DEV_ROLE_NAME}' not found. Run migrations first.")
            return

        # Assign the role (system scope — no study/site restriction)
        user_role = UserRole(
            user_id=user.id,
            role_id=role.id,
            study_id=None,
            site_id=None,
        )
        session.add(user_role)

        await session.commit()

        print("=" * 50)
        print("  Dev user created successfully!")
        print("=" * 50)
        print(f"  Email:    {DEV_USER_EMAIL}")
        print(f"  Password: {DEV_USER_PASSWORD}")
        print(f"  Role:     {DEV_ROLE_NAME}")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
