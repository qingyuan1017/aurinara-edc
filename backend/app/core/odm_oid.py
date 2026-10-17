"""Stable ODM object identifiers for Designer metadata."""

from __future__ import annotations

import re
from uuid import UUID, uuid4

_OID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,254}$")


def new_odm_oid(prefix: str, entity_id: UUID | None = None) -> str:
    """Return a stable, ODM-safe identifier derived from an immutable UUID."""
    value = entity_id or uuid4()
    return f"{prefix.upper()}.{value.hex.upper()}"


def is_valid_odm_oid(value: str) -> bool:
    """Validate the conservative OID subset used by the Aurinara profile."""
    return bool(_OID_PATTERN.fullmatch(value))


__all__ = ["is_valid_odm_oid", "new_odm_oid"]
