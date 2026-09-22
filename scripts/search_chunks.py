"""Run a semantic search query against the built chunk index.

A manual smoke-test/demo tool — the actual retrieval router (semantic /
relational / graph-guided hybrid) is a later phase; this exercises the
semantic path in isolation.

Usage:
    uv run python scripts/search_chunks.py "who audits NVIDIA's financials?" [--top-k 5]
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from entitygraph_rag.extraction.gemini_client import build_client
from entitygraph_rag.retrieval import DEFAULT_EMBEDDING_MODEL, DEFAULT_OUTPUT_DIMENSIONALITY, VectorIndex, semantic_search

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.jsonl"
INDEX_PATH = ROOT / "data" / "processed" / "chunk_index"


def load_chunks_by_id(path: Path) -> dict[str, dict]:
    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {chunk["chunk_id"]: chunk for chunk in chunks}


def main() -> None:
    # Chunk section labels carry an em dash (see chunker.py); Windows consoles
    # often default stdout to a non-UTF-8 codepage and mangle it otherwise.
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", type=str)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_OUTPUT_DIMENSIONALITY)
    args = parser.parse_args()

    if not INDEX_PATH.with_name(INDEX_PATH.name + ".ids.json").exists():
        raise SystemExit(f"{INDEX_PATH.relative_to(ROOT).as_posix()}.* not found — run scripts/build_index.py first")

    chunks_by_id = load_chunks_by_id(CHUNKS_PATH)
    index = VectorIndex.from_file(INDEX_PATH)
    client = build_client()

    results = semantic_search(
        args.query,
        index=index,
        chunks_by_id=chunks_by_id,
        client=client,
        model_name=args.model,
        output_dimensionality=args.dimensions,
        top_k=args.top_k,
    )

    print(f"Top {len(results)} results for: {args.query!r}\n")
    for rank, chunk in enumerate(results, start=1):
        preview = chunk["text"][:200].replace("\n", " ")
        print(f"{rank}. [{chunk['score']:.3f}] {chunk['ticker']} {chunk['form']} — {chunk['section']}")
        print(f"   {preview}...\n")


if __name__ == "__main__":
    main()
