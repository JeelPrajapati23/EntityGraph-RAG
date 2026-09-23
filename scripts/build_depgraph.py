"""Load the DepGraph node table and every edge file into a GraphStore.

Reads data/processed/depgraph/nodes.jsonl (from scripts/resolve_nodes.py)
and the edge files from Phases 2-4, loads them into a NetworkXGraphStore,
and saves it to data/processed/depgraph/graph.pkl. The finance graph at
data/processed/graph.pkl is not touched.

Then it checks, per corpus root, that a lockfile-scoped DEPENDS_ON walk
reaches exactly the versions that lockfile installs (read from the raw
lockfile, independently of the graph), and prints tree depth
and vulnerability exposure. It finishes with the plan's demo path:
axios@0.21.1 -> follow-redirects@1.13.1 [GHSA-74fj-2j2h-c42q / CVE-2022-0155].

Usage:
    uv run python scripts/build_depgraph.py
"""

import argparse
from pathlib import Path

from entitygraph_rag.graph import NetworkXGraphStore
from entitygraph_rag.graph.exposure import dependency_paths, exposure
from entitygraph_rag.npm.corpus import corpus_name_versions, read_jsonl
from entitygraph_rag.npm.graph_load import dependency_to_edge, record_to_edge, root_of_lockfile, to_entity
from entitygraph_rag.npm.vulnerabilities import version_id

ROOT = Path(__file__).resolve().parent.parent
DEPGRAPH_DIR = ROOT / "data" / "processed" / "depgraph"
LOCKFILE_MANIFEST = ROOT / "data" / "raw" / "lockfiles" / "manifest.jsonl"
GRAPH_PATH = DEPGRAPH_DIR / "graph.pkl"
RECORD_EDGE_FILES = ["vulnerability_edges.jsonl", "registry_edges.jsonl", "condition_edges.jsonl"]
DEMO = ("lockfile:npm:axios@0.21.1", "GHSA-74fj-2j2h-c42q")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    for name in ["nodes.jsonl", "dependency_edges.jsonl", *RECORD_EDGE_FILES]:
        if not (DEPGRAPH_DIR / name).exists():
            raise SystemExit(f"{name} not found in {DEPGRAPH_DIR.relative_to(ROOT).as_posix()}; "
                             f"run the Phase 2-4 scripts (last: scripts/resolve_nodes.py) first.")

    store = NetworkXGraphStore()
    store.load(
        (to_entity(n) for n in read_jsonl(DEPGRAPH_DIR / "nodes.jsonl")),
        [dependency_to_edge(r) for r in read_jsonl(DEPGRAPH_DIR / "dependency_edges.jsonl")]
        + [record_to_edge(r) for name in RECORD_EDGE_FILES for r in read_jsonl(DEPGRAPH_DIR / name)],
    )
    store.save_to_file(GRAPH_PATH)
    print(f"Loaded {store.node_count()} nodes, {store.edge_count()} edges -> {GRAPH_PATH.relative_to(ROOT).as_posix()}")

    corpus = corpus_name_versions(LOCKFILE_MANIFEST, ROOT)
    print("\nPer root (lockfile-scoped walk):")
    mismatched = []
    for record in read_jsonl(LOCKFILE_MANIFEST):
        doc_id, root_id = record["doc_id"], root_of_lockfile(record["doc_id"])
        paths = dependency_paths(store, root_id, doc_id)
        found = exposure(store, root_id, doc_id)
        expected = {version_id(name, version) for (name, version), docs in corpus.items() if doc_id in docs}
        if set(paths) != expected:
            mismatched.append((doc_id, len(set(paths) ^ expected)))
        deepest = max(found, key=lambda f: f["depth"]) if found else None
        print(f"  {record['root_name']}@{record['root_version']}: {len(paths)} versions reachable, "
              f"max depth {max(len(p) - 1 for p in paths.values())}, "
              f"{len({f['vulnerability_id'] for f in found})} advisories on "
              f"{len({f['version_id'] for f in found})} versions"
              + (f", deepest at {deepest['depth']} hops ({deepest['version_id']})" if deepest else ""))
    print(f"\nReachability check: {len(mismatched)} lockfiles where the walk differs from the installed set")
    for doc_id, n in mismatched:
        print(f"  {doc_id}: {n} versions differ")

    doc_id, vuln_id = DEMO
    print(f"\nDemo: is {root_of_lockfile(doc_id)} exposed to {vuln_id}?")
    for hit in exposure(store, root_of_lockfile(doc_id), doc_id, vulnerability_ids={vuln_id}):
        aliases = store.get_entity(vuln_id)["properties"]["aliases"]
        print("  " + " -> depends_on -> ".join(hit["path"]) + f" [VULNERABLE: {vuln_id} / {', '.join(aliases)}]")
    if mismatched:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
