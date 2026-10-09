"""Property-based test for post-migration published-design consumability.

# Feature: designer-edc-refactor, Property 16: Published designs remain consumable after migration

**Validates: Requirements 11.3**

After the migration reassignment runs, *every* pre-migration PUBLISHED study
version must remain a consumable ``Published_Design`` through the
``Design_Consumption_Contract`` (``DesignConsumptionService.get_published_design``),
while DRAFT versions are neither expected to be consumable nor falsely reported.

This test seeds random mixes of published and draft study versions (each
published version carrying design content), runs
``reassignment_service.reassign_all`` followed by
``VerificationService.verify``, and asserts:

  * ``result.published_designs_consumable`` equals *exactly* the set of
    pre-migration published version ids, and
  * ``result.failing_published_designs`` is empty (every published design is
    still consumable — R11.3), and draft versions never appear in either list.

The migration here is a code-layer ownership reassignment that rewrites no
stored value, so each published design must resolve to a published view
unchanged. The test runs against a real in-memory SQLite async session following
the same seeding/engine pattern as ``test_verification_service.py``.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  (register every ORM table for create_all)
from app.core.database import Base
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.services.designer.migration.reassignment_service import (
    reassignment_service,
)
from app.services.designer.migration.snapshot_service import snapshot_service
from app.services.designer.migration.verification_service import (
    VerificationResult,
    VerificationService,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A study carries an ordered list of version statuses. Keeping lists small keeps
# each Hypothesis example cheap (fresh in-memory DB per example) while still
# covering published-only, draft-only, and mixed studies. ``min_size=1`` so
# every study has at least one version; the overall mix across studies is varied
# by the outer list strategy.
_version_status = st.sampled_from(
    [StudyVersionStatus.published, StudyVersionStatus.draft]
)

# Each study is a list of version statuses (in creation order). Several studies
# per example exercise multiple published versions coexisting with drafts.
_studies_strategy = st.lists(
    st.lists(_version_status, min_size=1, max_size=4),
    min_size=1,
    max_size=4,
)

# Varied design content per published version: how many forms / fields / visits
# / codelist items it carries. Small bounds keep seeding fast.
_content_strategy = st.fixed_dictionaries(
    {
        "forms": st.integers(min_value=0, max_value=3),
        "fields": st.integers(min_value=0, max_value=3),
        "visits": st.integers(min_value=0, max_value=3),
        "codelist_items": st.integers(min_value=0, max_value=3),
    }
)


async def _seed_published_version_content(
    session: AsyncSession,
    version: StudyVersion,
    content: dict[str, int],
) -> None:
    """Attach varied design content to one published version.

    Mirrors the minimal-but-complete published design seeded in
    ``test_verification_service.py`` while varying counts so each published
    design carries a different, randomly-generated body of content.
    """
    for form_index in range(content["forms"]):
        form = FormDefinition(
            study_version_id=version.id,
            name=f"Form {form_index}",
            form_code=f"F{form_index}",
            display_order=form_index + 1,
            is_repeating=bool(form_index % 2),
        )
        session.add(form)
        await session.flush()
        section = FormSection(
            form_definition_id=form.id,
            name=f"Section {form_index}",
            display_order=1,
        )
        session.add(section)
        await session.flush()
        for field_index in range(content["fields"]):
            session.add(
                FieldDefinition(
                    form_section_id=section.id,
                    label=f"Field {field_index}",
                    variable_name=f"var_{form_index}_{field_index}",
                    control_type="text",
                    data_type="string",
                    is_required=bool(field_index % 2),
                    display_order=field_index + 1,
                )
            )

    for visit_index in range(content["visits"]):
        session.add(
            VisitDefinition(
                study_version_id=version.id,
                name=f"Visit {visit_index}",
                visit_number=visit_index + 1,
                visit_type="scheduled",
                display_order=visit_index + 1,
                is_required=True,
            )
        )

    if content["codelist_items"] > 0:
        codelist = Codelist(
            study_version_id=version.id,
            name="Codelist",
            code=f"CL{uuid.uuid4().hex[:6]}",
        )
        session.add(codelist)
        await session.flush()
        for item_index in range(content["codelist_items"]):
            session.add(
                CodelistItem(
                    codelist_id=codelist.id,
                    code=f"C{item_index}",
                    label=f"Label {item_index}",
                    display_order=item_index + 1,
                )
            )


async def _seed_mix(
    session: AsyncSession,
    studies: list[list[StudyVersionStatus]],
    content: dict[str, int],
) -> set[uuid.UUID]:
    """Seed the random mix of published/draft versions.

    Returns the set of PUBLISHED version ids — the exact set that must remain
    consumable after migration (R11.3). Draft versions are seeded but excluded.
    """
    published_ids: set[uuid.UUID] = set()
    for study_index, statuses in enumerate(studies):
        study = Study(
            study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
            title=f"Study {study_index}",
            status=StudyStatus.active,
            created_by=uuid.uuid4(),
        )
        session.add(study)
        await session.flush()
        for version_index, status in enumerate(statuses):
            version = StudyVersion(
                study_id=study.id,
                version_number=f"{version_index + 1}.0",
                status=status,
            )
            session.add(version)
            await session.flush()
            if status == StudyVersionStatus.published:
                published_ids.add(version.id)
                await _seed_published_version_content(session, version, content)
    await session.commit()
    return published_ids


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(studies=_studies_strategy, content=_content_strategy)
@pytest.mark.asyncio
async def test_published_designs_remain_consumable_after_migration(
    studies: list[list[StudyVersionStatus]],
    content: dict[str, int],
) -> None:
    """Every pre-migration published version stays consumable after reassign (R11.3).

    For any random mix of published/draft versions, running the migration
    reassignment then verification confirms the consumable set equals exactly the
    pre-migration published version ids and no published design is reported as
    failing. Draft versions appear in neither list.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        async with factory() as seed:
            published_ids = await _seed_mix(seed, studies, content)

        async with factory() as session:
            # Phase 0 snapshot, then Phase 4 reassignment (logical ownership
            # change — rewrites no stored value), then Phase 5 verification.
            pre_snapshot = await snapshot_service.capture(session)
            await reassignment_service.reassign_all(session)
            await session.commit()

            service = VerificationService()
            result = await service.verify(session, pre_snapshot)

        assert isinstance(result, VerificationResult)
        # Exactly the published versions are consumable — no more, no fewer.
        assert set(result.published_designs_consumable) == published_ids
        # No published design failed to resolve through the consumption contract.
        assert result.failing_published_designs == []
        # Draft versions are never falsely reported as consumable or failing.
        failing_ids = {
            f.design_version_id for f in result.failing_published_designs
        }
        assert published_ids.isdisjoint(failing_ids)
    finally:
        await engine.dispose()
