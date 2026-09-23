"""Turn a DepGraph router result into what the frontend draws: a {"nodes", "edges"} subgraph and fix plans.

Exposure, affected-projects, dependency-path and remediation rows each carry
a dependency path, drawn as DEPENDS_ON edges ending in HAS_VULNERABILITY
edges to the row's advisories. Neighbor rows are single edges. Semantic and
graph-guided-hybrid answers come from advisory text, so they yield an empty
graph. Rows are capped: react-scripts alone has 177 advisories in its tree.
"""

from ..graph import GraphStore, graph_node
from ..npm.remediation import summarize

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


def _step(text: str, command: str | None = None, kind: str = "step") -> dict:
    return {"text": text, "command": command, "kind": kind}


def _names(upgrades: dict) -> str:
    return ", ".join(f"{name} {u['from']} → {u['version']}" for name, u in sorted(upgrades.items()))


def plan_display(plan: dict, incomplete: list[str] | None = None) -> dict:
    """A plan as the page shows it: a short label, one line of why, and steps with copyable commands.

    Steps of kind "note" are context (no action). The override fallback is
    left out: the page draws it from the plan's `override`.
    """
    name, status, target = plan["package"], plan["status"], plan.get("target_version")
    notes = [_step(f"Release metadata for {', '.join(incomplete)} is missing, so this plan may miss fixed versions "
                   f"or upgrade paths.", kind="note")] if incomplete and status != "no_metadata" else []
    if status == "upgrade_root":
        return {"label": "upgrade the project", "why": "",
                "steps": notes + [_step(f"Upgrade {name} {plan['current_version']} → {target}.", f"npm install {name}@{target}")]}
    if status == "in_range":
        return {"label": "refresh the lockfile", "why": f"{name}@{target} fits every dependent's declared range.",
                "steps": notes + [_step("Refresh the lockfile:", f"npm update {name}")]}
    if status == "split":
        copies = "; ".join(f"{name}@{d['admits']} for {d['dependent'].removeprefix('npm:')} ({d['range']})"
                           for d in plan["dependents"])
        return {"label": "refresh the lockfile", "why": f"No single version fits every dependent, so npm installs "
                                                        f"separate copies: {copies}.",
                "steps": notes + [_step("Refresh the lockfile:", f"npm update {name}")]}
    if status not in ("blocked", "no_fix") or not plan.get("dependents"):
        # no_fix with nothing to upgrade, or no_metadata: the planner's own text is the whole story.
        return {"label": {"no_fix": "no fixed release", "no_metadata": "no release data"}.get(status, status.replace("_", " ")),
                "why": "", "steps": notes + [_step(a, kind="note") for a in plan.get("actions", [])]}

    blocked = [d for d in plan["dependents"] if d["admits"] is None]
    blockers = ", ".join(f"{d['dependent'].removeprefix('npm:').removeprefix('project:')} (\"{d['range']}\")"
                         for d in blocked[:3]) + (f" and {len(blocked) - 3} more" if len(blocked) > 3 else "")
    why = (f"No release of {name} newer than {plan['current_version']} is fixed, so it has to be dropped by "
           f"upgrading what depends on it: {blockers}." if status == "no_fix" else
           f"{name}@{target} is the lowest fixed version, but {blockers} "
           f"{'excludes' if len(blocked) == 1 else 'exclude'} every fixed version.")
    s = summarize(plan)
    steps = list(notes)
    for dep, m in sorted(s["manifest"].items()):
        steps.append(_step(f"In your package.json, change {dep} from \"{m['from']}\" to:", f'"{dep}": "{m["to"]}"'))
    if s["manifest"]:
        steps.append(_step("Reinstall:", "npm install"))
    for dep, u in sorted(s["root"].items()):
        steps.append(_step(f"Upgrade {dep} {u['from']} → {u['version']}.", f"npm install {dep}@{u['version']}"))
    if s["refresh"]:
        steps.append(_step(f"Refresh the lockfile to take {_names(s['refresh'])}; each fits the ranges its own "
                           f"dependents declare.", f"npm update {' '.join(sorted(s['refresh']))}"))
    if s["via"]:
        steps.append(_step(f"These come with it (lowest versions that work): {_names(s['via'])}.", kind="note"))
    if s["unchecked"]:
        steps.append(_step(f"Assumed to move together, not checked: {'; '.join(s['unchecked'])}.", kind="note"))
    if s["unresolved"]:
        steps.append(_step(f"No upgrade path for: {'; '.join(s['unresolved'])}.", kind="note"))
    fine = [d for d in plan["dependents"] if d["admits"] is not None]
    if fine:
        steps.append(_step("The other dependents already accept a fixed version after a lockfile refresh: "
                           + ", ".join(f"{d['dependent'].removeprefix('npm:')} → {name}@{d['admits']}" for d in fine[:3])
                           + (f" and {len(fine) - 3} more" if len(fine) > 3 else "") + ".", kind="note"))
    label = ("edit package.json" if s["manifest"] else "upgrade the project" if s["root"]
             else "upgrade dependents" if s["refresh"] or s["via"] else "no upgrade path")
    return {"label": label, "why": why, "steps": steps}


def fix_plans(result: dict) -> list[dict]:
    """A remediation result's rows as plan_summaries."""
    if (result.get("executed_pattern") or result.get("pattern")) != "remediation":
        return []
    return plan_summaries(result.get("results", []))


def plan_summaries(rows: list[dict]) -> list[dict]:
    """Remediation rows without the plan tree: status, steps (plan_display), and which path nodes the fix upgrades."""
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
        **plan_display({**row["plan"], "actions": row["actions"]}, row.get("incomplete")),
    } for row in rows[:MAX_FIX_PLANS]]
