"""Resolve raw extracted entity names into canonical entities.

Reads data/processed/triples.jsonl (from scripts/extract_triples.py) and
writes two files:
  - data/processed/entities.jsonl: one row per canonical entity
    (entity_id, canonical_name, entity_type, aliases).
  - data/processed/edges.jsonl: the same triples with subject_id/object_id
    added, referencing canonical entities — this is the input graph
    construction (Phase 3) will load.

Usage:
    uv run python scripts/resolve_entities.py
"""

import dataclasses
import json
from collections import Counter
from pathlib import Path

from entitygraph_rag.resolution import apply_resolution, load_company_registry, resolve_entities

ROOT = Path(__file__).resolve().parent.parent
TRIPLES_PATH = ROOT / "data" / "processed" / "triples.jsonl"
ENTITIES_OUT_PATH = ROOT / "data" / "processed" / "entities.jsonl"
EDGES_OUT_PATH = ROOT / "data" / "processed" / "edges.jsonl"


def load_triples(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    if not TRIPLES_PATH.exists():
        raise SystemExit(f"{TRIPLES_PATH.relative_to(ROOT).as_posix()} not found — run scripts/extract_triples.py first")

    triples = load_triples(TRIPLES_PATH)
    print(f"Resolving entities across {len(triples)} triples...")

    company_registry = load_company_registry()
    resolved = resolve_entities(triples, company_registry=company_registry)
    edges = apply_resolution(triples, resolved)

    unique_entities = {entity.entity_id: entity for entity in resolved.values()}
    by_type = Counter(entity.entity_type for entity in unique_entities.values())
    for entity_type, count in sorted(by_type.items()):
        print(f"  {entity_type}: {count} canonical entities")

    merged = sum(1 for entity in unique_entities.values() if len(entity.aliases) > 1)
    print(f"  {merged} canonical entities merged from 2+ surface forms")

    ENTITIES_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ENTITIES_OUT_PATH.open("w", encoding="utf-8") as f:
        for entity in sorted(unique_entities.values(), key=lambda e: e.entity_id):
            f.write(json.dumps(dataclasses.asdict(entity)) + "\n")

    with EDGES_OUT_PATH.open("w", encoding="utf-8") as f:
        for edge in edges:
            f.write(json.dumps(edge) + "\n")

    print(
        f"\nDone. {len(unique_entities)} entities -> {ENTITIES_OUT_PATH.relative_to(ROOT).as_posix()}, "
        f"{len(edges)} edges -> {EDGES_OUT_PATH.relative_to(ROOT).as_posix()}"
    )


if __name__ == "__main__":
    main()
