"""Pre-migration snapshot module (Migration Phase 0).

Records, for each design-time and operational record set, the row count and an
**order-independent value checksum** so that Phase 5 verification can confirm
the Migration_Process reassigned ownership without altering any stored value
(Requirements 11.1, 11.2, 11.5).

The snapshot captures ownership-reassigned sets only; the refactor is additive
and never renames or rewrites rows, so a byte-stable fingerprint of the current
rows is sufficient to detect post-migration drift.

Design notes
------------
* **Record sets.** Nine design-time sets (studies, study_versions,
  visit_definitions, form_definitions, form_sections, field_definitions,
  codelists, codelist_items, edit_checks) and five operational sets (subjects,
  visit_instances, form_instances, form_records, field_values — the "field
  values" set). These mirror the record sets named in R11.1/R11.2.
* **Count.** ``SELECT count(*)`` over every row (including soft-deleted rows —
  reassignment must preserve them too, R11.8-adjacent).
* **Value checksum.** Each row is serialized to a canonical form (its mapped
  columns sorted by name, every value normalized to a stable string), hashed
  with SHA-256, and the per-row digests are **summed modulo 2**:sup:`256`. Summation
  is commutative, so the set-level checksum is independent of row ordering while
  still being sensitive to any change in any field of any row.
* **Serializable structure.** :class:`MigrationSnapshot` and
  :class:`RecordSetSnapshot` expose ``to_dict`` / ``from_dict`` producing plain
  JSON-safe data that Phase 5 reads back to compare against a fresh snapshot.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.models.edc.edit_check import EditCheck
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.form_metadata import (
    Codelist,
    CodelistItem,
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.edc.form_record import FormRecord
from app.models.edc.study import Study, StudyVersion
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitDefinition, VisitInstance

# Snapshot format version — bump when the canonicalization scheme changes so a
# stored snapshot can never be silently compared under different rules.
SNAPSHOT_VERSION = 1

# The field-value set is named "field values" in R11.2; its backing table is
# ``field_values`` (the normalized per-field rows).
FIELD_VALUES_SET = "field_values"

# Ordered mapping of logical record-set name -> ORM model. Dict insertion order
# is preserved and reflected in the serialized snapshot, but the set-level
# checksum of each set is itself order-independent across rows.
RECORD_SET_MODELS: dict[str, type[Base]] = {
    # Design-time sets (reassigned to the Designer_Module — R11.1)
    "studies": Study,
    "study_versions": StudyVersion,
    "visit_definitions": VisitDefinition,
    "form_definitions": FormDefinition,
    "form_sections": FormSection,
    "field_definitions": FieldDefinition,
    "codelists": Codelist,
    "codelist_items": CodelistItem,
    "edit_checks": EditCheck,
    # Operational sets (reassigned to the EDC_Module — R11.2)
    "subjects": Subject,
    "visit_instances": VisitInstance,
    "form_instances": FormInstance,
    "form_records": FormRecord,
    FIELD_VALUES_SET: FieldValue,
}

# Design-time vs operational partition, exposed for callers that only need one
# half of the snapshot. Kept consistent with RECORD_SET_MODELS.
DESIGN_TIME_SETS: tuple[str, ...] = (
    "studies",
    "study_versions",
    "visit_definitions",
    "form_definitions",
    "form_sections",
    "field_definitions",
    "codelists",
    "codelist_items",
    "edit_checks",
)
OPERATIONAL_SETS: tuple[str, ...] = (
    "subjects",
    "visit_instances",
    "form_instances",
    "form_records",
    FIELD_VALUES_SET,
)

# Modulus for the order-independent checksum fold (256-bit).
_CHECKSUM_MODULUS = 1 << 256
_ZERO_CHECKSUM = "0" * 64


def _normalize_value(value: Any) -> str:
    """Return a stable, collision-resistant string for one column value.

    Each normalized value is prefixed with a type tag so that values of
    different types (for example the integer ``1`` and the string ``"1"``) can
    never produce the same canonical form.
    """
    if value is None:
        return "N:"
    if isinstance(value, bool):
        # bool is a subclass of int — handle it first for a distinct tag.
        return f"B:{int(value)}"
    if isinstance(value, Enum):
        return f"E:{value.value!r}"
    if isinstance(value, uuid.UUID):
        return f"U:{value}"
    if isinstance(value, (datetime, date)):
        # isoformat is lossless for aware/naive datetimes and dates.
        return f"T:{value.isoformat()}"
    if isinstance(value, Decimal):
        # Normalize so that e.g. Decimal("1.0") and Decimal("1.00") agree only
        # when numerically equal; use a canonical string form.
        return f"D:{value.normalize():f}"
    if isinstance(value, (int,)):
        return f"I:{value}"
    if isinstance(value, float):
        return f"F:{value!r}"
    if isinstance(value, (bytes, bytearray)):
        return "Y:" + bytes(value).hex()
    if isinstance(value, (dict, list, tuple)):
        return "J:" + _canonical_json(value)
    return f"S:{value!r}"


def _canonical_json(value: Any) -> str:
    """Order-independent canonical rendering of JSON-like structures.

    Dict keys are sorted; lists preserve order (JSON arrays are ordered). This
    gives a stable fingerprint for JSON/JSONB columns such as ``rule_json`` and
    ``data_jsonb`` regardless of the key ordering returned by the driver.
    """
    if isinstance(value, dict):
        inner = ",".join(
            f"{k!r}:{_canonical_json(value[k])}" for k in sorted(value, key=repr)
        )
        return "{" + inner + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(v) for v in value) + "]"
    return _normalize_value(value)


def _row_digest(model: type[Base], row: Base) -> int:
    """Compute the 256-bit integer digest of a single row.

    The row is rendered as its mapped columns sorted by name, each as
    ``name=normalized_value`` joined by ``\\x1f`` (unit separator), prefixed by
    the table name so identical column tuples in different tables never collide.
    """
    mapper = inspect(model)
    column_names = sorted(c.key for c in mapper.column_attrs)
    parts = [model.__tablename__]
    for name in column_names:
        parts.append(f"{name}={_normalize_value(getattr(row, name))}")
    canonical = "\x1f".join(parts)
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


@dataclass(frozen=True)
class RecordSetSnapshot:
    """Immutable snapshot of a single record set."""

    name: str
    table: str
    count: int
    checksum: str  # 64-char lowercase hex (256-bit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table": self.table,
            "count": self.count,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordSetSnapshot:
        return cls(
            name=data["name"],
            table=data["table"],
            count=int(data["count"]),
            checksum=data["checksum"],
        )


@dataclass(frozen=True)
class MigrationSnapshot:
    """A stable, serializable snapshot of all reassigned record sets.

    Fed to Phase 5 verification: a fresh snapshot taken after migration must
    equal this one set-for-set (count and checksum) or the migration is treated
    as data-losing and aborted (R11.5, R11.6).
    """

    version: int
    record_sets: dict[str, RecordSetSnapshot] = field(default_factory=dict)

    def get(self, name: str) -> RecordSetSnapshot | None:
        return self.record_sets.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "record_sets": {
                name: rs.to_dict() for name, rs in self.record_sets.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MigrationSnapshot:
        return cls(
            version=int(data["version"]),
            record_sets={
                name: RecordSetSnapshot.from_dict(rs)
                for name, rs in data.get("record_sets", {}).items()
            },
        )


class SnapshotService:
    """Builds pre-migration :class:`MigrationSnapshot` instances."""

    def __init__(
        self, record_set_models: dict[str, type[Base]] | None = None
    ) -> None:
        self._record_set_models = record_set_models or RECORD_SET_MODELS

    async def snapshot_record_set(
        self, session: AsyncSession, name: str, model: type[Base]
    ) -> RecordSetSnapshot:
        """Snapshot one record set: its row count and order-independent checksum."""
        count_result = await session.execute(select(func.count()).select_from(model))
        count = int(count_result.scalar_one())

        fold = 0
        rows_result = await session.execute(select(model))
        for row in rows_result.scalars():
            fold = (fold + _row_digest(model, row)) % _CHECKSUM_MODULUS

        checksum = _ZERO_CHECKSUM if count == 0 else format(fold, "064x")
        return RecordSetSnapshot(
            name=name,
            table=model.__tablename__,
            count=count,
            checksum=checksum,
        )

    async def capture(self, session: AsyncSession) -> MigrationSnapshot:
        """Capture a full pre-migration snapshot across all record sets."""
        record_sets: dict[str, RecordSetSnapshot] = {}
        for name, model in self._record_set_models.items():
            record_sets[name] = await self.snapshot_record_set(session, name, model)
        return MigrationSnapshot(version=SNAPSHOT_VERSION, record_sets=record_sets)


# Module-level singleton for convenience.
snapshot_service = SnapshotService()
