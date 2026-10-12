"""Property-based test for Design_Version amendment in the Designer module.

# Feature: designer-edc-refactor, Property 5: Amendment creates one draft and retains history

**Validates: Requirements 2.9, 2.11**

Property 5 (design.md): _For all_ Published_Designs and all amendments with a
reason of 1 to 4,000 characters inclusive, exactly one new Draft_Design is
created and every prior Published_Design version remains retrievable.

Requirement 2.9: WHEN an authorized Designer_Role user amends a Published_Design
with an amendment reason of 1 to 4,000 characters inclusive, THE Designer_Module
SHALL create one new Draft_Design.

Requirement 2.11: THE Designer_Module SHALL retain all prior Published_Design
versions for traceability.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.edc.study import Study
from app.services.designer.study_version_service import StudyVersionService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A history of 1+ published versions, keyed by distinct ascending major numbers.
published_major_versions = st.lists(
    st.integers(min_value=1, max_value=100),
    min_size=1,
    max_size=8,
    unique=True,
).map(sorted)

# Amendment reasons constrained to the valid 1-4,000 character window (R2.9).
# Includes boundary emphasis at length 1 and 4000 so the strategy exercises the
# full inclusive range rather than only mid-range values.
_reason_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Zs")),
    min_size=1,
    max_size=4000,
).filter(lambda value: 1 <= len(value.strip()) <= 4000)

amendment_reason_strategy = st.one_of(
    _reason_text,
    st.just("x"),  # minimum valid length after strip
    st.just("y" * 4000),  # maximum valid length
)


class InMemoryVersionRepository:
    """Repository double retaining published history across one service call.

    Mirrors the designer ``StudyVersionRepository`` contract used by
    ``create_amendment`` (``latest_published``, ``draft_for_study``, ``add``)
    without a database so the property exercises pure lifecycle logic.
    """

    def __init__(self, versions: list[StudyVersion]) -> None:
        self.versions = versions
        self.added: list[StudyVersion] = []

    async def latest_published(self, _session: object, study_id: uuid.UUID) -> StudyVersion | None:
        candidates = [
            v
            for v in self.versions
            if v.study_id == study_id and v.status == StudyVersionStatus.published
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda v: int(v.version_number.split(".", 1)[0]),
        )

    async def draft_for_study(self, _session: object, study_id: uuid.UUID) -> StudyVersion | None:
        return next(
            (
                v
                for v in self.versions
                if v.study_id == study_id and v.status == StudyVersionStatus.draft
            ),
            None,
        )

    async def add(self, _session: object, version: StudyVersion) -> StudyVersion:
        if version.id is None:
            version.id = uuid.uuid4()
        self.versions.append(version)
        self.added.append(version)
        return version


def _make_published_history(study_id: uuid.UUID, major_versions: list[int]) -> list[StudyVersion]:
    """Build a published-only version history for a study."""
    versions: list[StudyVersion] = []
    published_at = datetime(2024, 1, 1, tzinfo=UTC)
    for offset, major in enumerate(major_versions):
        versions.append(
            StudyVersion(
                id=uuid.uuid4(),
                study_id=study_id,
                version_number=f"{major}.0",
                status=StudyVersionStatus.published,
                amendment_reason=(f"Historical amendment {major}" if offset else None),
                published_at=published_at + timedelta(days=offset),
                published_by=uuid.uuid4(),
            )
        )
    return versions


def _snapshot(version: StudyVersion) -> tuple[object, ...]:
    """Capture every amendment-relevant field for an immutability comparison."""
    return (
        version.id,
        version.study_id,
        version.version_number,
        version.status,
        version.amendment_reason,
        version.amended_from_version_id,
        version.published_at,
        version.published_by,
    )


@given(major_versions=published_major_versions, reason=amendment_reason_strategy)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_amendment_creates_one_draft_and_retains_history(
    major_versions: list[int], reason: str
) -> None:
    """A valid amendment adds exactly one draft and never mutates history.

    Validates Requirement 2.9 (one new Draft_Design) and Requirement 2.11 (all
    prior Published_Design versions retained for traceability).
    """
    study_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    versions = _make_published_history(study_id, major_versions)

    original_versions = list(versions)
    original_snapshots = [_snapshot(v) for v in versions]
    original_published_ids = {v.id for v in versions}

    repository = InMemoryVersionRepository(versions)
    clone_service = AsyncMock()
    clone_service.clone_version.return_value = {}
    service = StudyVersionService(repository, clone_service=clone_service)
    session = AsyncMock()
    study = Study(
        id=study_id,
        study_code=f"AM-{uuid.uuid4().hex[:10]}",
        title="Designer Amendment Property Study",
        created_by=actor_id,
    )

    with patch("app.services.designer.study_version_service.audit_service") as mock_audit:
        mock_audit.record = AsyncMock()
        amendment = await service.create_amendment(session, study, reason, actor_id)

    source = original_versions[-1]

    # R2.9: exactly one new Draft_Design is created from the latest published version.
    assert repository.added == [amendment]
    assert amendment.status == StudyVersionStatus.draft
    assert amendment.version_number == f"{major_versions[-1] + 1}.0"
    assert amendment.amendment_reason == reason.strip()
    assert amendment.amended_from_version_id == source.id

    drafts = [v for v in repository.versions if v.status == StudyVersionStatus.draft]
    assert len(drafts) == 1
    assert drafts[0] is amendment

    # R2.11: every prior published version is retained, unchanged, and retrievable.
    retained_published = [
        v for v in repository.versions if v.status == StudyVersionStatus.published
    ]
    assert {v.id for v in retained_published} == original_published_ids
    assert [_snapshot(v) for v in retained_published] == original_snapshots

    # The amendment never replaces or deletes a prior published version.
    assert amendment.id not in original_published_ids
    assert len(retained_published) == len(original_versions)

    mock_audit.record.assert_awaited_once()
