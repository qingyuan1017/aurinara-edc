from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.edc.study import Study
from app.models.shared.identity import Role, ScopeLevel, User, UserRole
from app.services.shared.platform_projection_service import PlatformEvent, apply_platform_event


@pytest.mark.asyncio
async def test_projection_preserves_issuer_and_uses_edc_role_id() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    study_id = uuid4()
    local_role_id = uuid4()
    platform_role_id = local_role_id
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
                    "sponsor": "Platform Sponsor",
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
                    "product": "aurinara-edc",
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
        study = await session.get(Study, study_id)
        assert study is not None
        assert study.sponsor == "Platform Sponsor"

    await engine.dispose()


@pytest.mark.asyncio
async def test_projection_ignores_other_product_memberships() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        applied = await apply_platform_event(
            session,
            PlatformEvent(
                id=uuid4(),
                type="platform.membership.changed.v1",
                aggregate_id=uuid4(),
                sequence=1,
                data={
                    "study_id": str(uuid4()),
                    "user_id": str(uuid4()),
                    "product": "aurinara",
                    "site_id": None,
                    "role_ids": [],
                },
            ),
        )
        assert applied is False
        assert await session.scalar(select(UserRole)) is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_system_assignment_maps_platform_identity_to_local_user() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    local_user_id = uuid4()
    platform_user_id = uuid4()
    local_role_id = uuid4()
    platform_role_id = local_role_id

    async with factory() as session:
        session.add(
            User(
                id=local_user_id,
                email="admin@example.test",
                first_name="EDC",
                last_name="Admin",
                external_issuer="https://issuer.example",
                external_subject="subject-admin",
            )
        )
        session.add(
            Role(
                id=local_role_id,
                name="System Administrator",
                scope_level=ScopeLevel.system,
                is_system=True,
            )
        )
        await session.flush()

        await apply_platform_event(
            session,
            PlatformEvent(
                id=uuid4(),
                type="platform.assignment.changed.v1",
                aggregate_id=platform_user_id,
                sequence=4,
                data={
                    "user_id": str(platform_user_id),
                    "issuer": "https://issuer.example",
                    "subject": "subject-admin",
                    "product": "aurinara-edc",
                    "role_ids": [str(platform_role_id)],
                    "assigned_by": str(platform_user_id),
                },
            ),
        )
        await session.commit()

        assignment = await session.scalar(select(UserRole))
        assert assignment is not None
        assert assignment.user_id == local_user_id
        assert assignment.role_id == local_role_id
        assert assignment.study_id is None
        assert assignment.platform_managed is True

    await engine.dispose()
