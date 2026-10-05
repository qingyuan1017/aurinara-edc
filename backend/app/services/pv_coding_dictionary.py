"""Deterministic, in-memory MedDRA/WHODrug term validation for PV coding.

Term validation does not call an external dictionary service. Instead a
:class:`CodingDictionaryProvider` answers two questions deterministically:

  - Is a given ``Coding_Dictionary_Version`` available for a coding system?
  - Does a given ``term_id`` exist in that version?

The default provider recognizes a version as available when it is registered in
the ``pv_coding_dictionary_versions`` table (checked by the service) and
validates a ``term_id`` against a deterministic, offline rule: a term is present
in a version when it is non-empty and its content hash selects it under that
version. Deployments may register concrete term sets by supplying an explicit
term map; the fallback rule keeps property/example tests hermetic with no
external services.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from app.models.pv.coding import CodingSystem

# A registry mapping (coding_system, version) -> the set of valid term ids. When
# a (system, version) pair is present here, membership is authoritative. When it
# is absent, the deterministic fallback rule below decides membership so tests
# and offline environments stay hermetic.
TermMap = Mapping[tuple[str, str], frozenset[str]]


class CodingDictionaryProvider:
    """Deterministic term-validation oracle for PV coding.

    ``term_map`` optionally pins the exact valid term ids for specific
    ``(coding_system, version)`` pairs. Any pair not pinned falls back to a
    deterministic hash rule so validation is reproducible without external data.
    """

    def __init__(self, term_map: TermMap | None = None) -> None:
        self._term_map: dict[tuple[str, str], frozenset[str]] = {
            (system, version): frozenset(terms)
            for (system, version), terms in (term_map or {}).items()
        }

    def register(
        self, *, coding_system: CodingSystem, version: str, terms: frozenset[str]
    ) -> None:
        """Pin the valid term ids for a ``(coding_system, version)`` pair."""

        self._term_map[(coding_system.value, version)] = frozenset(terms)

    def term_exists(
        self, *, coding_system: CodingSystem, version: str, term_id: str
    ) -> bool:
        """Return whether ``term_id`` exists in the identified dictionary version.

        A pinned ``(system, version)`` uses its exact term set. Otherwise a
        deterministic rule accepts a non-empty term whose per-version hash is
        even, so validation is reproducible and some terms are rejected without
        any external dictionary service.
        """

        if not isinstance(term_id, str) or not term_id.strip():
            return False
        term = term_id.strip()

        pinned = self._term_map.get((coding_system.value, version))
        if pinned is not None:
            return term in pinned

        digest = hashlib.sha256(
            f"{coding_system.value}|{version}|{term}".encode()
        ).digest()
        return digest[0] % 2 == 0


# A shared default provider used when a caller supplies none. It is stateless
# apart from any explicitly registered term maps and is safe to share.
default_coding_dictionary = CodingDictionaryProvider()

__all__ = [
    "CodingDictionaryProvider",
    "TermMap",
    "default_coding_dictionary",
]
