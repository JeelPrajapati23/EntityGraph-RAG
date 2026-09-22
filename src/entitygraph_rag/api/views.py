"""Turn a router result into the {"nodes", "edges"} shape the frontend graph panel draws.

Mirrors synthesis/citations.py's graph_paths_for_result, but emits
structured node/edge records instead of path strings, so the traversal
behind a relational or graph-guided-hybrid answer can be highlighted
visually. The semantic route touches no graph, so it yields an empty graph.
"""

from ..graph import GraphStore


def _edges_for_result(result: dict) -> list[tuple[str, str, str]]:
    """(subject_id, relation, object_id) triples this result traversed."""
    edges = []
    if result["route"] == "relational":
        pattern = result.get("pattern", "neighbors")
        for row in result.get("results", []):
            if pattern == "common_neighbors":
                edges.extend((row["entity_id"], row["relation"], t["entity_id"]) for t in row["targets"])
            elif pattern == "two_hop":
                edges.append((row["source"]["entity_id"], row["first_relation"], row["via"]["entity_id"]))
                edges.append((row["via"]["entity_id"], row["relation"], row["target"]["entity_id"]))
            else:
                edges.append(_oriented(row))
    elif result["route"] == "graph_guided_hybrid":
        edges.extend(_oriented(row) for row in result.get("edges", []))
    return edges


def _oriented(row: dict) -> tuple[str, str, str]:
    source_id = row["source"]["entity_id"]
    if row["direction"] == "out":
        return (source_id, row["relation"], row["entity_id"])
    return (row["entity_id"], row["relation"], source_id)


def result_subgraph(result: dict, store: GraphStore) -> dict:
    triples = list(dict.fromkeys(_edges_for_result(result)))
    node_ids = sorted({node_id for s, _, o in triples for node_id in (s, o)})

    nodes = []
    for node_id in node_ids:
        entity = store.get_entity(node_id) or {}
        nodes.append({
            "entity_id": node_id,
            "canonical_name": entity.get("canonical_name", node_id),
            "entity_type": entity.get("entity_type"),
        })
    edges = [{"source": s, "target": o, "relation": relation or "related to"} for s, relation, o in triples]
    return {"nodes": nodes, "edges": edges}
