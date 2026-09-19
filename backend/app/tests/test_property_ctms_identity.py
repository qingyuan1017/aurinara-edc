"""Property-based verification of CTMS canonical identity stability.

**Validates: Requirements 1.3-1.7, 3.6, 4.7, 5.4, 6.7, 7.5-7.6, 9.4, 9.10-9.11**

Property 2: Canonical references are stable and unambiguous.

The resolver is exercised with a deterministic in-memory session.  Display
labels are deliberately mutable and may collide, while the canonical UUID is
the only accepted identity.  The fake records session state so rejected
references can be proven to have no side effects.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.query import Query
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject
from app.models.visit import VisitInstance
from app.services.ctms_identity_service import (
    CanonicalEntityType,
    CanonicalIdentityResolver,
)


class _Rows:
    """Minimal SQLAlchemy result facade for the deterministic repository fake."""

    def __init__(self, rows: list[object]):
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _IdentitySession:
    """Session fake that returns rows for the selected canonical ORM model."""

    def __init__(self, records: dict[type[object], list[object]]):
        self.records = records
        self.added: list[object] = []
        self.execute_count = 0

    async def execute(self, statement) -> _Rows:
        self.execute_count += 1
        model = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        matching_rows = []
        for record in self.records.get(model, []):
            if all(
                getattr(record, key.rsplit("_", 1)[0], object()) == value
                for key, value in params.items()
            ):
                matching_rows.append(record)
        return _Rows(matching_rows)

    def snapshot(self) -> tuple[tuple[type[object], tuple[tuple[str, object], ...]], ...]:
        """Capture persisted fake state, excluding the query counter."""

        return tuple(
            (
                model,
                tuple(
                    tuple(sorted(vars(record).items()))
                    for record in rows
                ),
            )
            for model, rows in sorted(self.records.items(), key=lambda item: item[0].__name__)
        )


_UUID = st.integers(min_value=1, max_value=2**128 - 1).map(lambda value: UUID(int=value))
_DISPLAY_NAME = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=24,
)


@st.composite
def canonical_maps(draw: st.DrawFn) -> dict[str, object]:
    """Generate canonical records and mutable/colliding display labels."""

    identifiers = draw(st.lists(_UUID, min_size=5, max_size=5, unique=True))
    labels = draw(st.lists(_DISPLAY_NAME, min_size=2, max_size=2))
    collision_label = draw(_DISPLAY_NAME)
    return {
        "study_id": identifiers[0],
        "site_id": identifiers[1],
        "subject_id": identifiers[2],
        "visit_id": identifiers[3],
        "query_id": identifiers[4],
        "label_before": labels[0],
        "label_after": labels[1],
        "collision_label": collision_label,
    }


_ENTITY_MODELS = {
    CanonicalEntityType.STUDY: Study,
    CanonicalEntityType.SITE: Site,
    CanonicalEntityType.SUBJECT: Subject,
    CanonicalEntityType.VISIT_INSTANCE: VisitInstance,
    CanonicalEntityType.QUERY: Query,
}


def _canonical_records(values: dict[str, object]) -> dict[CanonicalEntityType, SimpleNamespace]:
    """Build one canonical fake EDC record for every CTMS-referenceable type."""

    return {
        CanonicalEntityType.STUDY: SimpleNamespace(
            id=values["study_id"], display_name=values["label_before"]
        ),
        CanonicalEntityType.SITE: SimpleNamespace(
            id=values["site_id"],
            study_id=values["study_id"],
            display_name=values["label_before"],
        ),
        CanonicalEntityType.SUBJECT: SimpleNamespace(
            id=values["subject_id"],
            study_id=values["study_id"],
            site_id=values["site_id"],
            display_name=values["label_before"],
        ),
        CanonicalEntityType.VISIT_INSTANCE: SimpleNamespace(
            id=values["visit_id"],
            subject_id=values["subject_id"],
            display_name=values["label_before"],
        ),
        CanonicalEntityType.QUERY: SimpleNamespace(
            id=values["query_id"],
            study_id=values["study_id"],
            site_id=values["site_id"],
            subject_id=values["subject_id"],
            display_name=values["label_before"],
        ),
    }


def _session_for(
    records: dict[CanonicalEntityType, SimpleNamespace],
    *,
    ambiguous: CanonicalEntityType | None = None,
) -> _IdentitySession:
    """Create a session fake, optionally duplicating one canonical row."""

    persisted = {
        _ENTITY_MODELS[entity]: [record]
        for entity, record in records.items()
    }
    if ambiguous is not None:
        persisted[_ENTITY_MODELS[ambiguous]].append(records[ambiguous])
    return _IdentitySession(persisted)


def _scope_for(entity: CanonicalEntityType, values: dict[str, object]) -> dict[str, UUID]:
    if entity is CanonicalEntityType.SITE:
        return {"study_id": values["study_id"]}
    if entity in {CanonicalEntityType.SUBJECT, CanonicalEntityType.QUERY}:
        return {"study_id": values["study_id"], "site_id": values["site_id"]}
    if entity is CanonicalEntityType.VISIT_INSTANCE:
        return {"subject_id": values["subject_id"]}
    return {}


@given(values=canonical_maps())
@settings(max_examples=150, deadline=None)
@pytest.mark.asyncio
async def test_canonical_references_are_stable_and_unambiguous(values: dict[str, object]):
    """Repeated resolution preserves source identity despite mutable labels."""

    records = _canonical_records(values)
    session = _session_for(records)
    resolver = CanonicalIdentityResolver(session)

    for entity, record in records.items():
        resolved = await resolver.resolve(
            entity,
            record.id,
            **_scope_for(entity, values),
        )
        assert resolved.id == record.id
        assert resolved.source_identifier == record.id
        assert resolved.entity_type is entity

        metadata = resolved.link_metadata(
            target_reference=values["study_id"],
            ownership_rule_version=1,
            correlation_id=f"identity-{entity.value}",
        )
        assert metadata.source_module is Module.EDC
        assert metadata.source_identifier == record.id
        assert metadata.target_module is Module.CTMS
        assert metadata.as_dict()["source_identifier"] == str(record.id)

    # A display-name edit, including a collision with another generated label,
    # cannot change the canonical source identifier used by CTMS.
    records[CanonicalEntityType.SUBJECT].display_name = values["label_after"]
    records[CanonicalEntityType.SITE].display_name = values["collision_label"]
    records[CanonicalEntityType.QUERY].display_name = values["collision_label"]
    after_label_change = session.snapshot()
    for entity in (CanonicalEntityType.SUBJECT, CanonicalEntityType.SITE, CanonicalEntityType.QUERY):
        record = records[entity]
        resolved = await resolver.resolve(entity, record.id, **_scope_for(entity, values))
        assert resolved.source_identifier == record.id

    assert session.snapshot() == after_label_change
    assert session.added == []


@given(values=canonical_maps(), entity=st.sampled_from(list(CanonicalEntityType)))
@settings(max_examples=150, deadline=None)
@pytest.mark.asyncio
async def test_display_name_unknown_and_ambiguous_references_are_rejected_without_mutation(
    values: dict[str, object], entity: CanonicalEntityType
):
    """Display labels, missing IDs, and duplicate matches never mutate state."""

    records = _canonical_records(values)
    record = records[entity]

    # Display-name identity is rejected before the fake repository is queried.
    display_session = _session_for(records)
    display_before = display_session.snapshot()
    with pytest.raises(ValidationError) as display_error:
        await CanonicalIdentityResolver(display_session).resolve(
            entity,
            record.id,
            display_name=values["collision_label"],
            **_scope_for(entity, values),
        )
    assert display_error.value.details["reason"] == "DISPLAY_NAME_NOT_ALLOWED"
    assert display_session.execute_count == 0
    assert display_session.snapshot() == display_before
    assert display_session.added == []

    # An unknown source identifier is a failed event candidate and leaves both
    # the authoritative fake records and CTMS-side fake state unchanged.
    unknown_id = UUID(int=(record.id.int % (2**128 - 1)) + 1)
    existing_ids = {item.id for item in records.values()}
    while unknown_id in existing_ids:
        unknown_id = UUID(int=(unknown_id.int % (2**128 - 1)) + 1)
    unknown_session = _session_for(records)
    unknown_before = unknown_session.snapshot()
    with pytest.raises(NotFoundError) as missing_error:
        await CanonicalIdentityResolver(unknown_session).resolve(
            entity,
            unknown_id,
            **_scope_for(entity, values),
        )
    assert missing_error.value.details["reason"] == "RECORD_NOT_FOUND"
    assert unknown_session.snapshot() == unknown_before
    assert unknown_session.added == []

    # Duplicate matching rows model an ambiguous canonical reference.  The
    # resolver rejects it rather than choosing by a mutable display label.
    ambiguous_session = _session_for(records, ambiguous=entity)
    ambiguous_before = ambiguous_session.snapshot()
    with pytest.raises(ConflictError) as ambiguous_error:
        await CanonicalIdentityResolver(ambiguous_session).resolve(
            entity,
            record.id,
            **_scope_for(entity, values),
        )
    assert ambiguous_error.value.details["reason"] == "AMBIGUOUS_REFERENCE"
    assert ambiguous_session.snapshot() == ambiguous_before
    assert ambiguous_session.added == []
