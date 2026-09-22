"""Generic graph query helpers, written only against the GraphStore interface.

Since these only call GraphStore's public methods, they work unmodified
against any backend implementing that interface (NetworkX now, Neo4j
AuraDB later — see store.py). Named after the kind of multi-hop question
the dataset was curated to make answerable (see docs/dataset.md).
"""

from .store import GraphStore


def two_hop_neighbors(store: GraphStore, entity_id: str, *, relation: str | None = None) -> list[dict]:
    """Entities reachable by following `relation` (or any relation) two hops out from entity_id.

    Each result is {"via": <first-hop entity_id>, "target": <second-hop
    entity_id>, "relation": <second hop's relation>}. Skips second hops
    that land back on entity_id or the first-hop node itself.
    """
    first_hop = store.neighbors(entity_id, relation=relation, direction="out")
    seen = {entity_id, *(hop["entity_id"] for hop in first_hop)}

    results = []
    for hop1 in first_hop:
        for hop2 in store.neighbors(hop1["entity_id"], relation=relation, direction="out"):
            if hop2["entity_id"] in seen:
                continue
            results.append({"via": hop1["entity_id"], "target": hop2["entity_id"], "relation": hop2["relation"]})
    return results


def common_neighbors(
    store: GraphStore,
    entity_id_a: str,
    entity_id_b: str,
    *,
    relation: str | None = None,
    direction: str = "in",
) -> list[str]:
    """Entities connected to both entity_id_a and entity_id_b via `relation`.

    E.g. "who supplies both NVIDIA and Apple?" is
    common_neighbors(store, nvidia_id, apple_id, relation="SUPPLIES", direction="in").
    """
    a_neighbors = {n["entity_id"] for n in store.neighbors(entity_id_a, relation=relation, direction=direction)}
    b_neighbors = {n["entity_id"] for n in store.neighbors(entity_id_b, relation=relation, direction=direction)}
    return sorted(a_neighbors & b_neighbors)
