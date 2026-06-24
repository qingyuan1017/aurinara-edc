"""Property-based test for soft-deletion retention.

**Validates: Requirements 3.4, 6.4, 22.2, 27.3**

Property 22: Soft deletion retains records.

Generates random deletion reasons and entities and asserts:
  1. For subjects: soft_delete sets deleted_at/deleted_by/deletion_reason and the
     record STILL EXISTS physically in the database (not removed) — Req 22.2.
  2. For users: deactivate sets status=inactive and the record is retained — Req 3.4.
  3. A soft-deleted subject can still be queried directly by ID, but is excluded
     from normal listings (Req 6.4, 27.3 — retention for traceability).
  4. At least 100 iterations.

Uses in-memory SQLite to exercise real DB state. The full metadata includes
Postgres-only JSONB columns (form metadata) that SQLite cannot render, so only
the tables needed for this property are created (mirrors test_subject_routes.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import PaginationParams
from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.core.request_context import request_id_var
from app.core.security import hash_password
from app.models.identity import User, UserStatus
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.services.subject_service import SubjectService
from app.services.user_service import UserService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random non-empty deletion reasons (printable text).
reason_strategy = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        min_codepoint=32,
        max_codepoint=126,
    ),
).map(lambda s: s.strip() or "deletion reason")

# Random subject numbers (unique within a study, but each example uses a fresh DB).
subject_number_strategy = st.from_regex(r"[0-9]{3}-[0-9]{4}", fullmatch=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_engine_and_session():
    """Create an in-memory SQLite async engine with only the needed tables."""
    from app.models.audit import AuditEvent
    from app.models.site import StudySiteUser

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    tables = [
        m.__table__
        for m in (
            User,
            Study,
            StudyVersion,
            Site,
            StudySiteUser,
            Subject,
            AuditEvent,
        )
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, session_factory


async def _seed_study_site(session: AsyncSession) -> dict:
    """Seed an actor user, a study with a published version, and a site."""
    user = User(
        id=uuid.uuid4(),
        email=f"actor-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("pw"),
        first_name="Act",
        last_name="Or",
        status=UserStatus.active,
    )
    session.add(user)
    await session.flush()

    study = Study(
        id=uuid.uuid4(),
        study_code=f"S-{uuid.uuid4().hex[:6]}",
        title="Test Study",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=user.id,
        created_at=datetime.now(UTC),
    )
    session.add(version)

    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Test Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    session.add(site)
    await session.flush()

    return {"user": user, "study": study, "version": version, "site": site}


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestSoftDeletionRetentionProperty:
    """Property-based tests for soft-deletion retention.

    **Validates: Requirements 3.4, 6.4, 22.2, 27.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        subject_number=subject_number_strategy,
        reason=reason_strategy,
    )
    @pytest.mark.asyncio
    async def test_soft_delete_subject_retains_record(
        self,
        subject_number: str,
        reason: str,
    ):
        """soft_delete marks the subject and retains the physical record.

        **Validates: Requirements 22.2, 6.4, 27.3**

        For any subject and deletion reason:
          - deleted_at, deleted_by, and deletion_reason are populated.
          - The row STILL EXISTS in the database (no physical delete).
          - It can still be queried directly by primary key.
          - It is excluded from normal get_subject and list_subjects results.
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    seeded = await _seed_study_site(session)
                    svc = SubjectService()

                    subject = Subject(
                        id=uuid.uuid4(),
                        study_id=seeded["study"].id,
                        site_id=seeded["site"].id,
                        study_version_id=seeded["version"].id,
                        subject_number=subject_number,
                        status=SubjectStatus.screening,
                        created_by=seeded["user"].id,
                        created_at=datetime.now(UTC),
                    )
                    session.add(subject)
                    await session.flush()
                    subject_id = subject.id

                    # Act: soft delete
                    await svc.soft_delete(
                        session, subject, reason=reason, actor_id=seeded["user"].id
                    )

                    # Soft-delete metadata is populated.
                    assert subject.deleted_at is not None
                    assert subject.deleted_by == seeded["user"].id
                    assert subject.deletion_reason == reason

                    # The physical row still exists (queried WITHOUT the
                    # deleted_at filter) — proves it was not removed.
                    raw = await session.execute(
                        select(Subject).where(Subject.id == subject_id)
                    )
                    persisted = raw.scalars().first()
                    assert persisted is not None
                    assert persisted.id == subject_id
                    assert persisted.deleted_at is not None
                    assert persisted.deletion_reason == reason

                    # Excluded from normal get (filters deleted_at IS NULL).
                    with pytest.raises(NotFoundError):
                        await svc.get_subject(session, subject_id)

                    # Excluded from normal listings.
                    listing = await svc.list_subjects(
                        session,
                        study_id=seeded["study"].id,
                        pagination=PaginationParams(page=1, page_size=50),
                    )
                    listed_ids = {item.id for item in listing.items}
                    assert subject_id not in listed_ids
                    assert listing.total == 0
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)

    @settings(max_examples=100, deadline=None)
    @given(
        email_local=st.from_regex(r"[a-z][a-z0-9]{2,12}", fullmatch=True),
    )
    @pytest.mark.asyncio
    async def test_deactivate_user_retains_record(
        self,
        email_local: str,
    ):
        """deactivate sets status=inactive and retains the user record.

        **Validates: Requirements 3.4**

        For any active user:
          - After deactivate, status == inactive.
          - The user row STILL EXISTS in the database (retained for traceability).
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor = User(
                        id=uuid.uuid4(),
                        email=f"admin-{uuid.uuid4().hex[:8]}@test.local",
                        password_hash=hash_password("pw"),
                        first_name="Ad",
                        last_name="Min",
                        status=UserStatus.active,
                    )
                    target = User(
                        id=uuid.uuid4(),
                        email=f"{email_local}-{uuid.uuid4().hex[:6]}@test.local",
                        password_hash=hash_password("pw"),
                        first_name="Tar",
                        last_name="Get",
                        status=UserStatus.active,
                    )
                    session.add_all([actor, target])
                    await session.flush()
                    target_id = target.id

                    svc = UserService()
                    deactivated = await svc.deactivate(
                        session, user_id=target_id, actor_id=actor.id
                    )

                    # Status is inactive.
                    assert deactivated.status == UserStatus.inactive

                    # The user row STILL EXISTS in the database (retained).
                    raw = await session.execute(
                        select(User).where(User.id == target_id)
                    )
                    persisted = raw.scalars().first()
                    assert persisted is not None
                    assert persisted.id == target_id
                    assert persisted.status == UserStatus.inactive
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)
