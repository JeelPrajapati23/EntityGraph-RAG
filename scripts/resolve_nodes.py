"""Build the DepGraph node table and check that every edge endpoint resolves.

Reads the Phase 1 raw data and the Phase 2/3 edge files, then writes:
    data/processed/depgraph/nodes.jsonl            every node, one canonical id each
    data/processed/depgraph/registry_edges.jsonl   VERSION_OF, MAINTAINED_BY, LICENSED_UNDER
    data/processed/depgraph/condition_edges.jsonl  EXPLOITABLE_WHEN, near-duplicates merged per advisory

ExploitCondition nodes and condition_edges.jsonl come from
exploit_conditions.jsonl (scripts/extract_conditions.py). If that file is
missing they are skipped with a warning.

Every edge in dependency_edges, vulnerability_edges, registry_edges and
condition_edges is then checked against the node table. Any dangling
endpoint is printed and the script exits non-zero.

Usage:
    uv run python scripts/resolve_nodes.py
"""

import argparse
import json
from collections import Counter
from functools import cache
from pathlib import Path

from reachfix.conditions.merge import merge_conditions
from reachfix.npm.corpus import corpus_name_versions, read_jsonl
from reachfix.npm.nodes import build_nodes, dangling_endpoints, dependency_edge_endpoints
from reachfix.npm.projects import load_projects

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "depgraph"
PACKUMENT_DIR = RAW / "npm" / "packuments"


@cache
def load_packument(name: str) -> dict | None:
    path = PACKUMENT_DIR / f"{name.replace('/', '__')}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    required = {
        OUT_DIR / "dependency_edges.jsonl": "build_dependency_edges.py",
        OUT_DIR / "vulnerability_edges.jsonl": "build_vulnerability_edges.py",
    }
    for path, script in required.items():
        if not path.exists():
            raise SystemExit(f"{path.relative_to(ROOT).as_posix()} not found; run scripts/{script} first.")

    corpus = corpus_name_versions(RAW / "lockfiles" / "manifest.jsonl", ROOT)
    advisories = [json.loads((ROOT / r["local_path"]).read_text(encoding="utf-8"))
                  for r in read_jsonl(RAW / "osv" / "manifest.jsonl")]
    vulnerability_edges = read_jsonl(OUT_DIR / "vulnerability_edges.jsonl")
    fixed_targets = [(e["object_name"], e["object_version"]) for e in vulnerability_edges if e["relation"] == "FIXED_IN"]

    nodes, registry_edges = build_nodes(corpus, load_packument, advisories, load_projects(), fixed_targets)

    conditions_path = OUT_DIR / "exploit_conditions.jsonl"
    condition_edges = []
    if conditions_path.exists():
        raw_conditions = read_jsonl(conditions_path)
        condition_nodes, condition_edges = merge_conditions(raw_conditions)
        nodes.extend(condition_nodes)
        print(f"  {len(raw_conditions)} extracted conditions merged into {len(condition_nodes)} ExploitCondition nodes")
    else:
        print(f"  ! {conditions_path.relative_to(ROOT).as_posix()} not found; skipping ExploitCondition nodes")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "nodes.jsonl", nodes)
    write_jsonl(OUT_DIR / "registry_edges.jsonl", registry_edges)
    write_jsonl(OUT_DIR / "condition_edges.jsonl", condition_edges)

    by_type = Counter(n["node_type"] for n in nodes)
    print(f"\nDone. {len(nodes)} nodes -> {(OUT_DIR / 'nodes.jsonl').relative_to(ROOT).as_posix()}")
    for node_type, n in sorted(by_type.items()):
        print(f"  {node_type}: {n}")
    versions = [n for n in nodes if n["node_type"] == "PackageVersion"]
    print(f"  PackageVersion: {sum(v['properties']['in_tree'] for v in versions)} in a tree, "
          f"{sum(v['properties']['is_root'] for v in versions)} roots, "
          f"{sum(bool(v['properties']['deprecated']) for v in versions)} deprecated, "
          f"{sum(v['properties']['published'] is False for v in versions)} not found in the registry")
    for relation, n in sorted(Counter(e["relation"] for e in registry_edges).items()):
        print(f"  {relation}: {n}")

    shared = Counter(a for n in nodes if n["node_type"] == "Vulnerability"
                     for a in n["properties"]["aliases"] if a.startswith("CVE-"))
    print(f"  CVE ids shared by more than one advisory: {sum(c > 1 for c in shared.values())}")

    all_edges = [dependency_edge_endpoints(e) for e in read_jsonl(OUT_DIR / "dependency_edges.jsonl")]
    all_edges += vulnerability_edges + registry_edges + condition_edges
    dangling = dangling_endpoints(nodes, all_edges)
    print(f"\nEndpoint check: {len(all_edges)} edges, {len(dangling)} dangling endpoints")
    for relation, endpoint in dangling[:20]:
        print(f"  {relation}: {endpoint}")
    if dangling:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
