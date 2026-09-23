"""Resolve raw extracted entity names to canonical entities across a triples file.

Company entities try the fixed-universe registry first (ticker/name/alias
match, then fuzzy — see company_registry.py), since that's the highest-
confidence, lowest-cost path for the dominant node type. Anything that
doesn't match — including every non-Company node type — falls through to
generic fuzzy clustering, scoped per node type so e.g. a Person and a
Company never merge just by having similar names.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .cluster import cluster_names
from .company_registry import CompanyRegistry

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class ResolvedEntity:
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)


def _entity_id(entity_type: str, canonical_name: str) -> str:
    slug = _SLUG_RE.sub("-", canonical_name.lower()).strip("-")
    return f"{entity_type}:{slug}"


def resolve_entities(triples: list[dict], *, company_registry: CompanyRegistry) -> dict[tuple[str, str], ResolvedEntity]:
    """Return {(raw_name, entity_type): ResolvedEntity} covering every subject/object in triples."""
    names_by_type: dict[str, Counter] = defaultdict(Counter)
    for triple in triples:
        names_by_type[triple["subject_type"]][triple["subject"]] += 1
        names_by_type[triple["object_type"]][triple["object"]] += 1

    resolved: dict[tuple[str, str], ResolvedEntity] = {}
    aliases_by_id: dict[str, set[str]] = defaultdict(set)

    for entity_type, counts in names_by_type.items():
        unresolved_counts: Counter = Counter()
        for name, count in counts.items():
            if entity_type == "Company":
                match = company_registry.match(name)
                if match is not None:
                    entity_id = _entity_id("Company", match.name)
                    resolved[(name, entity_type)] = ResolvedEntity(entity_id, match.name, "Company")
                    aliases_by_id[entity_id].add(name)
                    continue
            unresolved_counts[name] = count

        if not unresolved_counts:
            continue

        clusters = cluster_names(unresolved_counts)
        for name in unresolved_counts:
            canonical_name = clusters[name]
            entity_id = _entity_id(entity_type, canonical_name)
            resolved[(name, entity_type)] = ResolvedEntity(entity_id, canonical_name, entity_type)
            aliases_by_id[entity_id].add(name)

    for entity in resolved.values():
        entity.aliases = sorted(aliases_by_id[entity.entity_id])

    return resolved


def apply_resolution(triples: list[dict], resolved: dict[tuple[str, str], ResolvedEntity]) -> list[dict]:
    """Return edges with subject_id/object_id added, referencing resolved canonical entities."""
    edges = []
    for triple in triples:
        subject = resolved[(triple["subject"], triple["subject_type"])]
        obj = resolved[(triple["object"], triple["object_type"])]
        edges.append({**triple, "subject_id": subject.entity_id, "object_id": obj.entity_id})
    return edges
