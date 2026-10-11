from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.shared.identity import Role, ScopeLevel, User, UserRole
from app.models.shared.platform_projection import PlatformRoleMapping
from app.services.shared.platform_projection_service import PlatformEvent, apply_platform_event


@pytest.mark.asyncio
async def test_projection_preserves_issuer_and_uses_reviewed_role_mapping() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    study_id = uuid4()
    platform_role_id = uuid4()
    local_role_id = uuid4()
    issuer = "https://issuer.example"

    async with factory() as session:
        await apply_platform_event(
            session,
            PlatformEvent(
                id=uuid4(),
                type="platform.user.created.v1",
                aggregate_id=user_id,
                sequence=1,
                data={
                    "issuer": issuer,
                    "subject": "subject-1",
                    "email": "user@example.test",
                    "display_name": "Test User",
                    "status": "active",
                },
            ),
        )
        await apply_platform_event(
            session,
            PlatformEvent(
                id=uuid4(),
                type="platform.study.created.v1",
                aggregate_id=study_id,
                sequence=1,
                data={
                    "code": "STUDY-1",
                    "display_name": "Study One",
                    "status": "active",
                    "created_by": str(user_id),
                },
            ),
        )
        session.add(
            Role(
                id=local_role_id,
                name="Mapped Data Entry",
                scope_level=ScopeLevel.study,
                is_system=False,
            )
        )
        session.add(
            PlatformRoleMapping(
                platform_role_id=platform_role_id,
                local_role_id=local_role_id,
            )
        )
        await session.flush()
        await apply_platform_event(
            session,
            PlatformEvent(
                id=uuid4(),
                type="platform.membership.changed.v1",
                aggregate_id=study_id,
                sequence=2,
                data={
                    "study_id": str(study_id),
                    "user_id": str(user_id),
                    "site_id": None,
                    "role_ids": [str(platform_role_id)],
                    "assigned_by": str(user_id),
                },
            ),
        )
        await session.commit()

        user = await session.get(User, user_id)
        assert user is not None
        assert user.external_issuer == issuer
        assignments = (await session.execute(UserRole.__table__.select())).mappings().all()
        assert len(assignments) == 1
        assert assignments[0]["role_id"] == local_role_id
        assert assignments[0]["platform_role_id"] == platform_role_id

    await engine.dispose()
