"""Property-based tests for study-version amendments.

# Feature: clinical-edc-system, Property 11: Amendment preserves prior versions and binds forms to one version

**Validates: Requirements 5.3, 5.4, 5.5**

The amendment service must create a new draft from the latest published version
without modifying the published history or changing the owning version of any
existing form definition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.form_metadata import FormDefinition
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.services.study_version_service import StudyVersionService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

published_major_versions = st.lists(
    st.integers(min_value=1, max_value=100),
    min_size=1,
    max_size=8,
    unique=True,
).map(sorted)

amendment_reason_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Zs")),
    min_size=1,
    max_size=100,
).filter(lambda value: bool(value.strip()))


class InMemoryAmendmentRepository:
    """Minimal repository double retaining versions across a service call."""

    def __init__(self, versions: list[StudyVersion]) -> None:
        self.versions = versions
        self.added: list[StudyVersion] = []

    async def latest_published(self, _session: object, study_id: uuid.UUID) -> StudyVersion | None:
        candidates = [
            version
            for version in self.versions
            if version.study_id == study_id and version.status == StudyVersionStatus.published
        ]
        return (
            max(candidates, key=lambda version: int(version.version_number.split(".", 1)[0]))
            if candidates
            else None
        )

    async def draft_for_study(self, _session: object, study_id: uuid.UUID) -> StudyVersion | None:
        return next(
            (
                version
                for version in self.versions
                if version.study_id == study_id and version.status == StudyVersionStatus.draft
            ),
            None,
        )

    async def add(self, _session: object, version: StudyVersion) -> StudyVersion:
        if version.id is None:
            version.id = uuid.uuid4()
        self.versions.append(version)
        self.added.append(version)
        return version


def _make_published_history(
    study_id: uuid.UUID, major_versions: list[int]
) -> tuple[list[StudyVersion], list[FormDefinition]]:
    """Create published versions and one form bound to each version."""
    versions: list[StudyVersion] = []
    forms: list[FormDefinition] = []
    published_at = datetime(2024, 1, 1, tzinfo=UTC)

    for offset, major in enumerate(major_versions):
        version = StudyVersion(
            id=uuid.uuid4(),
            study_id=study_id,
            version_number=f"{major}.0",
            status=StudyVersionStatus.published,
            amendment_reason=(f"Historical amendment {major}" if offset else None),
            published_at=published_at + timedelta(days=offset),
            published_by=uuid.uuid4(),
        )
        versions.append(version)
        forms.append(
            FormDefinition(
                id=uuid.uuid4(),
                study_version_id=version.id,
                name=f"Form {major}",
                form_code=f"F{major}",
                display_order=offset,
                is_repeating=False,
            )
        )

    return versions, forms


def _version_snapshot(version: StudyVersion) -> tuple[object, ...]:
    """Capture every amendment-relevant field before the service runs."""
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
async def test_amendment_retains_published_history_and_form_ownership(
    major_versions: list[int], reason: str
) -> None:
    """Any valid amendment leaves prior versions and their form bindings immutable."""
    study_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    versions, forms = _make_published_history(study_id, major_versions)
    original_versions = list(versions)
    original_version_snapshots = [_version_snapshot(version) for version in versions]
    original_form_owners = {form.id: form.study_version_id for form in forms}
    repository = InMemoryAmendmentRepository(versions)
    service = StudyVersionService(repository)
    session = AsyncMock()
    study = Study(
        id=study_id,
        study_code=f"AM-{uuid.uuid4().hex[:10]}",
        title="Amendment Property Study",
        created_by=actor_id,
    )

    with patch("app.services.study_version_service.audit_service") as mock_audit:
        mock_audit.record = AsyncMock()
        amendment = await service.create_amendment(session, study, reason, actor_id)

    latest_source = original_versions[-1]
    assert amendment.status == StudyVersionStatus.draft
    assert amendment.version_number == f"{major_versions[-1] + 1}.0"
    assert amendment.amendment_reason == reason.strip()
    assert amendment.amended_from_version_id == latest_source.id
    assert repository.added == [amendment]

    # Every published version remains present with all amendment-relevant fields unchanged.
    retained_published = [
        version for version in repository.versions if version.status == StudyVersionStatus.published
    ]
    assert [
        _version_snapshot(version) for version in retained_published
    ] == original_version_snapshots
    assert {version.id for version in retained_published} == {
        version.id for version in original_versions
    }

    # Existing form definitions remain bound to exactly their original version.
    assert len({form.id for form in forms}) == len(forms)
    assert all(form.study_version_id is not None for form in forms)
    assert {form.id: form.study_version_id for form in forms} == original_form_owners
    assert all(
        form.study_version_id in {version.id for version in original_versions} for form in forms
    )
    assert amendment.id not in {form.study_version_id for form in forms}

    mock_audit.record.assert_awaited_once()
