"""Run a query through the full retrieval router (semantic / relational / graph-guided-hybrid).

Loads every artifact the pipeline so far has produced — chunks, the vector
index, the resolved entities, and the graph — classifies the query with an
LLM call, and prints whichever route it dispatched to and the results.

Usage:
    uv run python scripts/query.py "who supplies NVIDIA?"
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from reachfix.extraction.schema import load_schema
from reachfix.graph import NetworkXGraphStore
from reachfix.llm_client import build_client
from reachfix.retrieval import VectorIndex, build_embedding_client
from reachfix.router import EntityLookup, route_query

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.jsonl"
ENTITIES_PATH = ROOT / "data" / "processed" / "entities.jsonl"
GRAPH_PATH = ROOT / "data" / "processed" / "graph.pkl"
INDEX_PATH = ROOT / "data" / "processed" / "chunk_index"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", type=str)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    missing = [p for p in (CHUNKS_PATH, ENTITIES_PATH, GRAPH_PATH) if not p.exists()]
    if missing:
        names = ", ".join(p.relative_to(ROOT).as_posix() for p in missing)
        raise SystemExit(f"missing required file(s): {names} — run build_chunks/resolve_entities/build_graph first")

    chunks_by_id = {c["chunk_id"]: c for c in load_jsonl(CHUNKS_PATH)}
    entities = load_jsonl(ENTITIES_PATH)
    store = NetworkXGraphStore.from_file(GRAPH_PATH)
    index = VectorIndex.from_file(INDEX_PATH)
    entity_lookup = EntityLookup(entities)
    schema = load_schema()
    client = build_client()
    embedding_client = build_embedding_client()

    result = route_query(
        args.query,
        client=client,
        embedding_client=embedding_client,
        schema=schema,
        store=store,
        index=index,
        chunks_by_id=chunks_by_id,
        entity_lookup=entity_lookup,
        top_k=args.top_k,
    )

    print(f"Route: {result['route']}  ({result['classification_reasoning']})\n")

    if result["route"] == "relational":
        print(f"Pattern: {result['pattern']}")
        if result.get("warning"):
            print(f"Warning: {result['warning']}")
        for item in result["results"]:
            print(f"  {item}")
    elif result["route"] == "graph_guided_hybrid":
        names = ", ".join(e["canonical_name"] for e in result["expanded_entities"])
        print(f"Expanded entities: {names or '(none resolved)'}\n")
        for chunk in result["chunks"]:
            preview = chunk["text"][:200].replace("\n", " ")
            print(f"  [{chunk['score']:.3f}] {chunk['ticker']} {chunk['form']} — {chunk['section']}\n    {preview}...\n")
    else:
        for chunk in result["chunks"]:
            preview = chunk["text"][:200].replace("\n", " ")
            print(f"  [{chunk['score']:.3f}] {chunk['ticker']} {chunk['form']} — {chunk['section']}\n    {preview}...\n")


if __name__ == "__main__":
    main()
