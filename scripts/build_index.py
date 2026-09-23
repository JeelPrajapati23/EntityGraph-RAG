"""Embed every chunk and build a searchable vector index.

Reads data/processed/chunks.jsonl (from scripts/build_chunks.py), embeds
each chunk via the Hugging Face Inference API (cached per chunk in
.cache/embeddings/, keyed on chunk text + model + output dimensionality),
and writes the resulting index to
data/processed/chunk_index.{vectors.npy,ids.json}.

Usage:
    uv run python scripts/build_index.py [--tickers NVDA,AAPL]
        [--doc-type filings|transcripts|both] [--limit N]
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from reachfix.retrieval import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_OUTPUT_DIMENSIONALITY,
    VectorIndex,
    build_embedding_client,
    embed_chunks,
)

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.jsonl"
INDEX_PATH = ROOT / "data" / "processed" / "chunk_index"
CACHE_ROOT = ROOT / ".cache" / "embeddings"

DOC_TYPE_CHOICES = {
    "filings": ["filing"],
    "transcripts": ["transcript"],
    "both": ["filing", "transcript"],
}


def load_chunks(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker subset (default: all)")
    parser.add_argument("--doc-type", choices=sorted(DOC_TYPE_CHOICES), default="both")
    parser.add_argument("--limit", type=int, default=None, help="Max chunks to process (cost control during dev)")
    parser.add_argument("--model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_OUTPUT_DIMENSIONALITY)
    args = parser.parse_args()

    if not CHUNKS_PATH.exists():
        raise SystemExit(f"{CHUNKS_PATH.relative_to(ROOT).as_posix()} not found — run scripts/build_chunks.py first")

    chunks = load_chunks(CHUNKS_PATH)

    wanted_doc_types = set(DOC_TYPE_CHOICES[args.doc_type])
    chunks = [c for c in chunks if c["doc_type"] in wanted_doc_types]
    if args.tickers:
        wanted_tickers = {t.strip().upper() for t in args.tickers.split(",")}
        chunks = [c for c in chunks if c["ticker"].upper() in wanted_tickers]
    if args.limit:
        chunks = chunks[: args.limit]

    print(f"Embedding {len(chunks)} chunks with {args.model} ({args.dimensions}-dim)...")

    client = build_embedding_client()
    chunk_ids, vectors = embed_chunks(
        chunks, client=client, model_name=args.model, output_dimensionality=args.dimensions, cache_root=CACHE_ROOT
    )

    index = VectorIndex(chunk_ids, vectors)
    index.save_to_file(INDEX_PATH)

    print(f"\nDone. {len(chunk_ids)} vectors indexed -> {INDEX_PATH.relative_to(ROOT).as_posix()}.*")


if __name__ == "__main__":
    main()
