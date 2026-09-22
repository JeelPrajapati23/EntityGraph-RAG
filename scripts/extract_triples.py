"""Extract typed, source-cited (entity, relation, entity) triples from chunks.

Reads data/processed/chunks.jsonl (from scripts/build_chunks.py), runs each
chunk through Gemini with structured output constrained to schema/v1.yaml's
vocabulary, validates each returned triple's subject/object type against its
relation before accepting it, and writes the accepted edges to
data/processed/triples.jsonl. Results are cached per chunk in .cache/
extraction/ (keyed on chunk text + model + schema version) so re-runs during
development don't re-spend tokens on unchanged chunks.

Usage:
    uv run python scripts/extract_triples.py [--tickers NVDA,AAPL]
        [--doc-type filings|transcripts|both] [--limit N] [--model NAME]
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from entitygraph_rag.extraction import build_client, build_system_prompt, build_triple_model, extract_for_chunk, load_schema
from entitygraph_rag.extraction.gemini_client import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.jsonl"
OUT_PATH = ROOT / "data" / "processed" / "triples.jsonl"
CACHE_ROOT = ROOT / ".cache" / "extraction"

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
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
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

    schema = load_schema()
    triple_model = build_triple_model(schema)
    system_prompt = build_system_prompt(schema)
    client = build_client()

    print(f"Extracting from {len(chunks)} chunks with {args.model} (schema v{schema.version})...")

    all_edges = []
    for i, chunk in enumerate(chunks, start=1):
        edges, warnings = extract_for_chunk(
            chunk,
            schema=schema,
            triple_model=triple_model,
            client=client,
            model_name=args.model,
            system_prompt=system_prompt,
            cache_root=CACHE_ROOT,
        )
        all_edges.extend(edges)
        for w in warnings:
            print(f"  ! {w}")

        if i % 25 == 0 or i == len(chunks):
            print(f"  [{i}/{len(chunks)}] {len(all_edges)} edges so far")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for edge in all_edges:
            f.write(json.dumps(edge) + "\n")

    print(f"\nDone. {len(all_edges)} edges written to {OUT_PATH.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
