"""Chunk OSV advisory `details` text for Phase 3's LLM extraction.

Reads data/raw/osv/manifest.jsonl (from scripts/fetch_osv.py), splits each
advisory's markdown `details` at headings and paragraphs, and packs it into
chunks of at most ~450 words (see entitygraph_rag.npm.advisory). Chunk ids
are "<osv_id>::<index>" and each chunk links back to the
advisory's osv.dev page. Malicious-package (MAL-) advisories are skipped.

Output (gitignored), fully rewritten each run:
    data/processed/depgraph/advisory_chunks.jsonl

Usage:
    uv run python scripts/build_advisory_chunks.py
"""

import argparse
import dataclasses
import json
from pathlib import Path

from entitygraph_rag.npm.advisory import chunk_advisory, is_malicious
from entitygraph_rag.npm.corpus import read_jsonl

ROOT = Path(__file__).resolve().parent.parent
OSV_MANIFEST = ROOT / "data" / "raw" / "osv" / "manifest.jsonl"
OUT_PATH = ROOT / "data" / "processed" / "depgraph" / "advisory_chunks.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    if not OSV_MANIFEST.exists():
        raise SystemExit("No OSV manifest; run scripts/fetch_osv.py first.")

    chunks = []
    skipped = []
    advisories = 0
    for record in read_jsonl(OSV_MANIFEST):
        advisory = json.loads((ROOT / record["local_path"]).read_text(encoding="utf-8"))
        if is_malicious(advisory):
            skipped.append(advisory["id"])
            continue
        advisories += 1
        chunks.extend(chunk_advisory(advisory))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(dataclasses.asdict(chunk)) + "\n")

    multi = len({c.doc_id for c in chunks if c.chunk_index})
    print(f"Done. {len(chunks)} chunks from {advisories} advisories ({multi} split into more than one) -> "
          f"{OUT_PATH.relative_to(ROOT).as_posix()}")
    if skipped:
        print(f"  skipped {len(skipped)} malicious-package advisories: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
