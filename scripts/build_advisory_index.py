"""Embed advisory chunks for semantic retrieval (HF Inference API).

Reads data/processed/depgraph/advisory_chunks.jsonl (from
scripts/build_advisory_chunks.py) and embeds it as one of the variants in
reachfix.npm.advisory_index (a model plus how chunks are fed to it).
Vectors are cached per window and model in .cache/embeddings/, so a re-run
only embeds what changed.

Output (gitignored):
    data/processed/depgraph/advisory_index_<variant>.{vectors.npy,ids.json}

Usage:
    uv run python scripts/build_advisory_index.py [--variant NAME | --all]
"""

import argparse
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from reachfix.npm.advisory_index import DEFAULT_VARIANT, VARIANTS, build_advisory_index, index_path
from reachfix.npm.corpus import read_jsonl
from reachfix.retrieval import build_embedding_client
from reachfix.retrieval.windows import parent_chunk_id

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "processed" / "depgraph" / "advisory_chunks.jsonl"
DEPGRAPH = ROOT / "data" / "processed" / "depgraph"
CACHE_ROOT = ROOT / ".cache" / "embeddings"


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default=DEFAULT_VARIANT)
    parser.add_argument("--all", action="store_true", help="Build every variant")
    args = parser.parse_args()

    if not CHUNKS_PATH.exists():
        raise SystemExit(f"{CHUNKS_PATH.relative_to(ROOT).as_posix()} not found; run scripts/build_advisory_chunks.py first.")
    chunks = read_jsonl(CHUNKS_PATH)
    client = build_embedding_client()

    for variant in (sorted(VARIANTS) if args.all else [args.variant]):
        print(f"Embedding {len(chunks)} advisory chunks ({variant}, {VARIANTS[variant].model})...", flush=True)
        index = build_advisory_index(chunks, client=client, cache_root=CACHE_ROOT, variant=variant)
        path = index_path(DEPGRAPH, variant)
        index.save_to_file(path)
        per_chunk = Counter(parent_chunk_id(w) for w in index.chunk_ids)
        print(f"  {len(index.chunk_ids)} vectors for {len(per_chunk)} chunks "
              f"(max {max(per_chunk.values())} per chunk) -> {path.relative_to(ROOT).as_posix()}.*", flush=True)


if __name__ == "__main__":
    main()
