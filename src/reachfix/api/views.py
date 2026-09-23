"""Turn a DepGraph router result into the {"nodes", "edges"} shape the frontend graph panel draws.

Exposure, affected-projects, dependency-path and remediation rows each carry
a dependency path, drawn as DEPENDS_ON edges ending in HAS_VULNERABILITY
edges to the row's advisories. Neighbor rows are single edges. Semantic and
graph-guided-hybrid answers come from advisory text, so they yield an empty
graph. Rows are capped: react-scripts alone has 177 advisories in its tree.
"""

from ..graph import GraphStore

MAX_DRAWN_ROWS = 40  # rows arrive ranked (worst severity / shallowest first)


def _advisory_ids(row: dict) -> list[str]:
    if row.get("vulnerability_id"):
        return [row["vulnerability_id"]]
    return [a["vulnerability_id"] for a in row.get("vulnerabilities", []) + row.get("advisories", [])]


def _edges_for_result(result: dict) -> list[tuple[str, str, str]]:
    """(subject_id, relation, object_id) triples this result traversed."""
    if result.get("executed_route") != "relational":
        return []
    rows = result.get("results", [])[:MAX_DRAWN_ROWS]
    if (result.get("executed_pattern") or result.get("pattern")) == "neighbors":
        edges = []
        for row in rows:
            source, other = row["source"]["node_id"], row["node_id"]
            edges.append((source, row["relation"], other) if row["direction"] == "out" else (other, row["relation"], source))
        return edges

    edges = []
    for row in rows:
        path = row.get("path", [])
        edges.extend((a, "DEPENDS_ON", b) for a, b in zip(path, path[1:]))
        edges.extend((row["version_id"], "HAS_VULNERABILITY", v) for v in _advisory_ids(row))
    return edges


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
    edges = [{"source": s, "target": o, "relation": relation} for s, relation, o in triples]
    return {"nodes": nodes, "edges": edges}
