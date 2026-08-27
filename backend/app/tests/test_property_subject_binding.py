"""Property-based test for subject binding and instance initialization.

**Validates: Requirements 7.1, 7.4, 8.2**

Property 12: Subject binding and instance initialization.

Generates random subject creation scenarios (study with published version, site,
visit definitions, form definitions) and asserts that after create_subject():
  1. The subject is bound to the published study version (Req 7.1).
  2. Visit instances are created from the version's visit definitions (Req 8.2).
  3. Form instances are created from the version's form definitions (Req 7.4).

Uses in-memory SQLite database with only the needed tables created.
At least 50 iterations with real DB interaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.request_context import request_id_var
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import (
    Codelist,
    CodelistItem,
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.identity import User, UserStatus
from app.models.site import Site, SiteStatus, StudySiteUser
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitDefinition, VisitInstance
from app.schemas.subject import SubjectCreate
from app.services.subject_service import SubjectService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Number of visit definitions per study version (at least 1 to verify initialization).
num_visits_strategy = st.integers(min_value=1, max_value=5)

# Number of form definitions per study version (at least 1 to verify initialization).
num_forms_strategy = st.integers(min_value=1, max_value=4)

# Random subject numbers.
subject_number_strategy = st.from_regex(r"[0-9]{3}-[0-9]{4}", fullmatch=True)

# Random visit names (printable ASCII, non-empty).
visit_name_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(min_codepoint=65, max_codepoint=90),
).map(lambda s: f"Visit {s[:20]}")

# Random form names (printable ASCII, non-empty).
form_name_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(min_codepoint=65, max_codepoint=90),
).map(lambda s: f"Form {s[:20]}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_engine_and_session():
    """Create an in-memory SQLite async engine with only the needed tables."""
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
            VisitDefinition,
            VisitInstance,
            FormDefinition,
            FormSection,
            FieldDefinition,
            Codelist,
            CodelistItem,
            FormInstance,
            FieldValue,
            AuditEvent,
        )
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, session_factory


async def _seed_study_with_definitions(
    session: AsyncSession,
    num_visits: int,
    num_forms: int,
    visit_names: list[str],
    form_names: list[str],
) -> dict:
    """Seed a user, study with published version, site, visit and form definitions."""
    user = User(
        id=uuid.uuid4(),
        email=f"actor-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("pw"),
        first_name="Test",
        last_name="Actor",
        status=UserStatus.active,
    )
    session.add(user)
    await session.flush()

    study = Study(
        id=uuid.uuid4(),
        study_code=f"STD-{uuid.uuid4().hex[:6]}",
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
    await session.flush()

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

    # Create visit definitions
    visit_defs = []
    for i in range(num_visits):
        vd = VisitDefinition(
            id=uuid.uuid4(),
            study_version_id=version.id,
            name=visit_names[i] if i < len(visit_names) else f"Visit {i + 1}",
            visit_number=i + 1,
            visit_type="scheduled",
            target_day=i * 7,
            window_before=3,
            window_after=3,
            display_order=i,
            is_required=True,
            created_at=datetime.now(UTC),
        )
        session.add(vd)
        visit_defs.append(vd)
    await session.flush()

    # Create form definitions
    form_defs = []
    for i in range(num_forms):
        fd = FormDefinition(
            id=uuid.uuid4(),
            study_version_id=version.id,
            name=form_names[i] if i < len(form_names) else f"Form {i + 1}",
            form_code=f"F{i + 1:02d}",
            display_order=i,
            is_repeating=False,
            created_at=datetime.now(UTC),
        )
        session.add(fd)
        form_defs.append(fd)
    await session.flush()

    return {
        "user": user,
        "study": study,
        "version": version,
        "site": site,
        "visit_defs": visit_defs,
        "form_defs": form_defs,
    }


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestSubjectBindingAndInitializationProperty:
    """Property-based tests for subject binding and instance initialization.

    **Validates: Requirements 7.1, 7.4, 8.2**
    """

    @settings(max_examples=50, deadline=None)
    @given(
        subject_number=subject_number_strategy,
        num_visits=num_visits_strategy,
        num_forms=num_forms_strategy,
        visit_names=st.lists(visit_name_strategy, min_size=5, max_size=5),
        form_names=st.lists(form_name_strategy, min_size=4, max_size=4),
    )
    @pytest.mark.asyncio
    async def test_subject_bound_to_published_version_with_instances(
        self,
        subject_number: str,
        num_visits: int,
        num_forms: int,
        visit_names: list[str],
        form_names: list[str],
    ):
        """create_subject binds the subject to the published version and
        initializes visit and form instances.

        **Validates: Requirements 7.1, 7.4, 8.2**

        For any combination of visit definitions (1–5) and form definitions (1–4):
          - The subject's study_version_id matches the published version (Req 7.1).
          - One VisitInstance per VisitDefinition is created (Req 8.2).
          - One FormInstance per (VisitInstance × FormDefinition) is created (Req 7.4).
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    seeded = await _seed_study_with_definitions(
                        session, num_visits, num_forms, visit_names, form_names
                    )

                    svc = SubjectService()
                    data = SubjectCreate(
                        site_id=seeded["site"].id,
                        subject_number=subject_number,
                    )

                    # Act
                    subject = await svc.create_subject(
                        session,
                        study_id=seeded["study"].id,
                        data=data,
                        actor_id=seeded["user"].id,
                    )

                    # -------------------------------------------------------
                    # Assert 1: Subject is bound to the published version (Req 7.1)
                    # -------------------------------------------------------
                    assert subject.study_version_id == seeded["version"].id
                    assert subject.status == SubjectStatus.screening

                    # -------------------------------------------------------
                    # Assert 2: Visit instances created from definitions (Req 8.2)
                    # -------------------------------------------------------
                    visit_result = await session.execute(
                        select(VisitInstance).where(
                            VisitInstance.subject_id == subject.id
                        )
                    )
                    visit_instances = list(visit_result.scalars().all())

                    assert len(visit_instances) == num_visits

                    # Each visit instance maps to a unique visit definition
                    visit_def_ids = {
                        vi.visit_definition_id for vi in visit_instances
                    }
                    expected_def_ids = {vd.id for vd in seeded["visit_defs"]}
                    assert visit_def_ids == expected_def_ids

                    # -------------------------------------------------------
                    # Assert 3: Form instances created from definitions (Req 7.4)
                    # -------------------------------------------------------
                    form_result = await session.execute(
                        select(FormInstance).where(
                            FormInstance.subject_id == subject.id
                        )
                    )
                    form_instances = list(form_result.scalars().all())

                    # One form instance per (visit_instance × form_definition)
                    expected_form_count = num_visits * num_forms
                    assert len(form_instances) == expected_form_count

                    # Each form instance is linked to a valid visit instance
                    form_visit_ids = {
                        fi.visit_instance_id for fi in form_instances
                    }
                    actual_visit_ids = {vi.id for vi in visit_instances}
                    assert form_visit_ids == actual_visit_ids

                    # Each form instance references a valid form definition
                    form_def_ids = {
                        fi.form_definition_id for fi in form_instances
                    }
                    expected_form_def_ids = {fd.id for fd in seeded["form_defs"]}
                    assert form_def_ids == expected_form_def_ids

            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)
