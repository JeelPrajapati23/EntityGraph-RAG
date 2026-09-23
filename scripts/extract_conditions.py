"""Extract EXPLOITABLE_WHEN edges (advisory -> ExploitCondition) from advisory chunks.

Reads data/processed/depgraph/advisory_chunks.jsonl (from
scripts/build_advisory_chunks.py). Each chunk goes to Groq with a prompt and
output model generated from schema/v2.yaml's `llm` edges only. Every
condition must quote its evidence verbatim, and one whose quote isn't in the
text is dropped (see entitygraph_rag.conditions.pipeline).

Results are cached per chunk in .cache/conditions/ (keyed on prompt + chunk
text + model + schema version), so an interrupted run resumes where it
stopped. The run stops after MAX_CONSECUTIVE_API_ERRORS Groq errors in a row
(e.g. a daily quota) and still writes what it has.

Output (gitignored), rewritten each run:
    data/processed/depgraph/exploit_conditions.jsonl

Usage:
    uv run python scripts/extract_conditions.py [--limit N] [--ids GHSA-...,GHSA-...] [--model NAME]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import groq
from dotenv import load_dotenv

from entitygraph_rag.conditions import build_extraction_model, build_system_prompt, extract_conditions
from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.llm_client import DEFAULT_MODEL, build_client
from entitygraph_rag.npm.corpus import read_jsonl

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "v2.yaml"
CHUNKS_PATH = ROOT / "data" / "processed" / "depgraph" / "advisory_chunks.jsonl"
OUT_PATH = ROOT / "data" / "processed" / "depgraph" / "exploit_conditions.jsonl"
CACHE_ROOT = ROOT / ".cache" / "conditions"
MAX_CONSECUTIVE_API_ERRORS = 3


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="Max chunks to process (cost control)")
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated advisory ids (default: all)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args()

    if not CHUNKS_PATH.exists():
        raise SystemExit(f"{CHUNKS_PATH.relative_to(ROOT).as_posix()} not found; run scripts/build_advisory_chunks.py first.")

    chunks = read_jsonl(CHUNKS_PATH)
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        chunks = [c for c in chunks if c["doc_id"] in wanted]
    if args.limit:
        chunks = chunks[: args.limit]

    schema = load_schema(SCHEMA_PATH)
    model = build_extraction_model(schema)
    system_prompt = build_system_prompt(schema)
    client = build_client()
    print(f"Extracting from {len(chunks)} chunks with {args.model} (schema v{schema.version})...")

    edges, dropped, failed, done = [], 0, [], []
    consecutive_errors = 0
    for i, chunk in enumerate(chunks, start=1):
        try:
            chunk_edges, warnings = extract_conditions(
                chunk, schema=schema, model=model, client=client, model_name=args.model,
                system_prompt=system_prompt, cache_root=CACHE_ROOT,
            )
        except groq.APIError as exc:
            failed.append(chunk["chunk_id"])
            consecutive_errors += 1
            print(f"  ! {chunk['chunk_id']}: Groq error ({exc.__class__.__name__}: {exc})")
            if consecutive_errors >= MAX_CONSECUTIVE_API_ERRORS:
                print(f"  ! {consecutive_errors} API errors in a row; stopping. Re-run to resume from the cache.")
                break
            continue
        consecutive_errors = 0
        done.append(chunk)
        edges.extend(chunk_edges)
        for w in warnings:
            dropped += "dropped" in w
            print(f"  ! {w}")
        if i % 25 == 0 or i == len(chunks):
            print(f"  [{i}/{len(chunks)}] {len(edges)} conditions so far", flush=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for edge in edges:
            f.write(json.dumps(edge) + "\n")

    advisories = {c["doc_id"] for c in done}
    with_conditions = {e["subject"] for e in edges}
    print(f"\nDone. {len(done)} of {len(chunks)} chunks processed. {len(edges)} conditions on "
          f"{len(with_conditions)} of {len(advisories)} processed advisories -> {OUT_PATH.relative_to(ROOT).as_posix()}")
    print(f"  by category: {dict(Counter(e['category'] for e in edges).most_common())}")
    print(f"  dropped for evidence not in text: {dropped}")
    if len(done) < len(chunks):
        print(f"  {len(chunks) - len(done)} chunks not processed ({len(failed)} Groq errors, the rest after the stop); "
              f"re-run to resume")


if __name__ == "__main__":
    main()
