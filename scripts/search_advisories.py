"""Semantic search over advisory text (Phase 6), optionally limited to one package.

Embeds the query, searches the windowed advisory index
(scripts/build_advisory_index.py) and prints the best chunks, one per line,
with their advisory, packages, score and osv.dev link.

--package limits the search to advisories affecting that package. The name
goes through NodeLookup, so "follow redirects" or a typo still resolves.
This is the candidate-scoped search the graph-guided hybrid route will use.

Usage:
    uv run python scripts/search_advisories.py "slow regex on crafted input" [--package lodash] [--top-k 5]
"""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from reachfix.npm.advisory_index import DEFAULT_VARIANT, VARIANTS, embed_query, index_path
from reachfix.npm.corpus import read_jsonl
from reachfix.npm.lookup import NodeLookup
from reachfix.retrieval import VectorIndex, build_embedding_client
from reachfix.retrieval.windows import search_chunks

ROOT = Path(__file__).resolve().parent.parent
DEPGRAPH = ROOT / "data" / "processed" / "depgraph"


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--package", default=None, help="Only advisories affecting this package")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default=DEFAULT_VARIANT)
    args = parser.parse_args()

    chunks = read_jsonl(DEPGRAPH / "advisory_chunks.jsonl")
    candidates = None
    if args.package:
        [node_id, *_] = NodeLookup(read_jsonl(DEPGRAPH / "nodes.jsonl")).resolve(args.package) or [None]
        if node_id is None or not node_id.startswith("npm:") or "@" in node_id[5:]:
            raise SystemExit(f"{args.package!r} doesn't resolve to a package in the corpus")
        name = node_id.removeprefix("npm:")
        candidates = {c["chunk_id"] for c in chunks if name in c["affected_packages"]}
        print(f"Limited to {name}: {len(candidates)} chunks")

    client = build_embedding_client()
    results = search_chunks(
        args.query, index=VectorIndex.from_file(index_path(DEPGRAPH, args.variant)),
        chunks_by_id={c["chunk_id"]: c for c in chunks}, client=client, top_k=args.top_k,
        candidate_chunk_ids=candidates, query_vector=embed_query(client, args.query, args.variant),
    )
    for r in results:
        print(f"{r['score']:.3f}  {r['chunk_id']:28} [{', '.join(r['affected_packages'])}] {r['summary'][:80]}\n"
              f"       {r['source_url']}")


if __name__ == "__main__":
    main()
