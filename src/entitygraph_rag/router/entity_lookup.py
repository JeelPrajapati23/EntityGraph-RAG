"""Resolve a human-typed entity name (from a query) to a canonical entity_id.

Reuses the aliases each entity already accumulated during resolution
(entities.jsonl — see resolution/resolve.py) rather than re-running fuzzy
clustering per query: exact normalized-alias match first, then a fuzzy
fallback across every known alias.
"""

from rapidfuzz import fuzz, process

from ..resolution.normalize import normalize_name

FUZZY_MATCH_THRESHOLD = 85


class EntityLookup:
    def __init__(self, entities: list[dict]):
        self.entities_by_id = {entity["entity_id"]: entity for entity in entities}
        self._entity_id_by_normalized_alias: dict[str, str] = {}
        for entity in entities:
            for alias in [entity["canonical_name"], *entity["aliases"]]:
                self._entity_id_by_normalized_alias[normalize_name(alias)] = entity["entity_id"]

    def resolve(self, name: str) -> str | None:
        normalized = normalize_name(name)
        if normalized in self._entity_id_by_normalized_alias:
            return self._entity_id_by_normalized_alias[normalized]

        if not self._entity_id_by_normalized_alias:
            return None

        best = process.extractOne(
            normalized, self._entity_id_by_normalized_alias.keys(), scorer=fuzz.token_sort_ratio
        )
        if best is not None and best[1] >= FUZZY_MATCH_THRESHOLD:
            return self._entity_id_by_normalized_alias[best[0]]
        return None
