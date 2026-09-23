"""Build a queryable graph from resolved entities/edges.

Reads data/processed/entities.jsonl and data/processed/edges.jsonl (from
scripts/resolve_entities.py), loads them into a GraphStore, saves it to
data/processed/graph.pkl, and runs a couple of hand-written smoke-test
queries as a sanity check (they double as demo queries later — the kind of
multi-hop question the dataset was curated to make answerable, see
docs/dataset.md).

Usage:
    uv run python scripts/build_graph.py
"""

import json
from pathlib import Path

from reachfix.graph import NetworkXGraphStore, common_neighbors, two_hop_neighbors

ROOT = Path(__file__).resolve().parent.parent
ENTITIES_PATH = ROOT / "data" / "processed" / "entities.jsonl"
EDGES_PATH = ROOT / "data" / "processed" / "edges.jsonl"
GRAPH_PATH = ROOT / "data" / "processed" / "graph.pkl"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_smoke_queries(store: NetworkXGraphStore, entities: list[dict]) -> None:
    companies = [e for e in entities if e["entity_type"] == "Company"]
    suppliers_with_out_edges = [
        c for c in companies if store.neighbors(c["entity_id"], relation="SUPPLIES", direction="out")
    ]

    if not suppliers_with_out_edges:
        print("\nSmoke test: no SUPPLIES edges in this graph yet, skipping 2-hop/common-neighbor demo.")
        return

    sample = suppliers_with_out_edges[0]
    print(f"\nSmoke test: SUPPLIES edges out of {sample['canonical_name']}")
    for n in store.neighbors(sample["entity_id"], relation="SUPPLIES", direction="out"):
        target = store.get_entity(n["entity_id"])
        name = target["canonical_name"] if target else n["entity_id"]
        print(f"  --SUPPLIES--> {name} (confidence {n['confidence']:.2f}, {len(n['provenance'])} mention(s))")

    two_hop = two_hop_neighbors(store, sample["entity_id"], relation="SUPPLIES")
    print(f"\nSmoke test: 2-hop SUPPLIES chains from {sample['canonical_name']}: {len(two_hop)} found")
    for hop in two_hop[:5]:
        via = store.get_entity(hop["via"])
        target = store.get_entity(hop["target"])
        print(f"  -> {via['canonical_name'] if via else hop['via']} -> {target['canonical_name'] if target else hop['target']}")

    if len(suppliers_with_out_edges) >= 2:
        a, b = suppliers_with_out_edges[0], suppliers_with_out_edges[1]
        shared = common_neighbors(store, a["entity_id"], b["entity_id"], relation="SUPPLIES", direction="in")
        print(f"\nSmoke test: companies supplying both {a['canonical_name']} and {b['canonical_name']}: {len(shared)}")


def main() -> None:
    if not ENTITIES_PATH.exists() or not EDGES_PATH.exists():
        raise SystemExit("entities.jsonl/edges.jsonl not found — run scripts/resolve_entities.py first")

    entities = load_jsonl(ENTITIES_PATH)
    edges = load_jsonl(EDGES_PATH)

    store = NetworkXGraphStore()
    store.load(entities, edges)
    print(f"Loaded {store.node_count()} nodes, {store.edge_count()} edges")

    store.save_to_file(GRAPH_PATH)
    print(f"Saved to {GRAPH_PATH.relative_to(ROOT).as_posix()}")

    run_smoke_queries(store, entities)


if __name__ == "__main__":
    main()
