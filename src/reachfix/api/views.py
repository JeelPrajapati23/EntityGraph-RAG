"""Turn a DepGraph router result into what the frontend draws: a {"nodes", "edges"} subgraph and fix plans.

Exposure, affected-projects, dependency-path and remediation rows each carry
a dependency path, drawn as DEPENDS_ON edges ending in HAS_VULNERABILITY
edges to the row's advisories. Neighbor rows are single edges. Semantic and
graph-guided-hybrid answers come from advisory text, so they yield an empty
graph. Rows are capped: react-scripts alone has 177 advisories in its tree.
"""

from ..graph import GraphStore, graph_node

MAX_DRAWN_ROWS = 40  # rows arrive ranked (worst severity / shallowest first)
MAX_FIX_PLANS = 10


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

    edges = [{"source": s, "target": o, "relation": relation} for s, relation, o in triples]
    return {"nodes": [graph_node(store, node_id) for node_id in node_ids], "edges": edges}


def _upgrades(plan: dict) -> dict[str, str]:
    """version id -> the version id the plan moves it to: the copy itself and each blocking dependent's upgrade."""
    out = {}
    if plan.get("target_version") and "package" in plan:  # an uploaded project's edit_manifest step has none
        out[plan["version_id"]] = f"npm:{plan['package']}@{plan['target_version']}"
    for dependent in plan.get("dependents", []):
        if dependent["admits"] is None and dependent.get("upgrade"):
            out.update({k: v for k, v in _upgrades(dependent["upgrade"]).items() if k not in out})
    return out


def fix_plans(result: dict) -> list[dict]:
    """A remediation result's rows as plan_summaries."""
    if (result.get("executed_pattern") or result.get("pattern")) != "remediation":
        return []
    return plan_summaries(result.get("results", []))


def plan_summaries(rows: list[dict]) -> list[dict]:
    """Remediation rows without the plan tree: status, steps, and which path nodes the fix upgrades."""
    return [{
        "project": row["project"],
        "dev_only": row.get("dev_only", False),
        "version_id": row["version_id"],
        "path": row["path"],
        "status": row["plan"]["status"],
        "target_version": row["plan"].get("target_version"),
        "resolved": row["resolved"],
        "actions": row["actions"],
        "override": row["plan"].get("override"),
        "advisories": [{"vulnerability_id": a["vulnerability_id"], "severity": a.get("severity")}
                       for a in row["advisories"]],
        "upgrades": _upgrades(row["plan"]),
    } for row in rows[:MAX_FIX_PLANS]]
