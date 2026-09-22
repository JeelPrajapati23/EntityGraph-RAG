"""Turn raw filings/transcripts into clean, chunked, source-traceable text.

Reads data/raw/{filings,transcripts}/manifest.jsonl (either may be missing —
skipped with a warning rather than failing the run), sections each document
(10-K/10-Q/8-K/20-F by Item boundary, 6-K/transcripts as a single unit or by
speaker turn), packs sections into ~450-word chunks, and writes the combined
result to data/processed/chunks.jsonl. Fully regenerates that file each run,
same as the two fetch_*.py scripts fully rewrite their own manifest.jsonl.

Usage:
    uv run python scripts/build_chunks.py [--tickers NVDA,AAPL] [--doc-type filings|transcripts|both]
"""

import argparse
from pathlib import Path

from entitygraph_rag.ingestion import load_manifest, process_filing, process_transcript, write_jsonl

ROOT = Path(__file__).resolve().parent.parent
FILINGS_MANIFEST = ROOT / "data" / "raw" / "filings" / "manifest.jsonl"
TRANSCRIPTS_MANIFEST = ROOT / "data" / "raw" / "transcripts" / "manifest.jsonl"
OUT_PATH = ROOT / "data" / "processed" / "chunks.jsonl"

PROCESSORS = {
    "filing": (FILINGS_MANIFEST, process_filing),
    "transcript": (TRANSCRIPTS_MANIFEST, process_transcript),
}
DOC_TYPE_CHOICES = {
    "filings": ["filing"],
    "transcripts": ["transcript"],
    "both": ["filing", "transcript"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker subset (default: all)")
    parser.add_argument("--doc-type", choices=sorted(DOC_TYPE_CHOICES), default="both")
    args = parser.parse_args()

    wanted_tickers = {t.strip().upper() for t in args.tickers.split(",")} if args.tickers else None
    doc_types = DOC_TYPE_CHOICES[args.doc_type]

    all_chunks = []
    doc_count = 0

    for doc_type in doc_types:
        manifest_path, process_fn = PROCESSORS[doc_type]
        records = load_manifest(manifest_path)
        if records is None:
            print(f"  ! manifest not found: {manifest_path.relative_to(ROOT).as_posix()}, skipping {doc_type}s")
            continue

        for record in records:
            if wanted_tickers and record["ticker"].upper() not in wanted_tickers:
                continue

            form = record.get("form", "transcript")
            date = record["filing_date"]
            try:
                chunks = process_fn(record, ROOT)
            except Exception as exc:
                print(f"  ! {record['ticker']} {form} {date}: failed to parse ({exc.__class__.__name__}: {exc}), skipping")
                continue

            all_chunks.extend(chunks)
            doc_count += 1
            n_sections = len({c.section_ordinal for c in chunks})
            print(f"  {record['ticker']} {form} {date}: {n_sections} sections, {len(chunks)} chunks")

    write_jsonl(OUT_PATH, all_chunks)
    print(f"\nDone. {len(all_chunks)} chunks from {doc_count} documents written to {OUT_PATH.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
