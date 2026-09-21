"""Fetch earnings-call transcripts for the configured company universe.

Source: Bose345/sp500_earnings_transcripts on Hugging Face (MIT licensed,
"research and educational use" per the dataset card) — speaker-segmented
S&P 500 earnings calls, 2005-2025. See docs/dataset.md for why this dataset
was picked, its coverage gap (TSM/ASML/STM are foreign private issuers, not
S&P 500 constituents, so they have no transcripts here), and a note on the
per-call copyright boilerplate embedded in the transcript text itself.

Queries Hugging Face's server-side dataset-viewer `/filter` API rather than
downloading the dataset's ~1GB parquet file — only matching rows cross the
wire. Output goes to data/raw/transcripts/ (gitignored).

Usage:
    uv run python scripts/fetch_transcripts.py [--tickers NVDA,AAPL] [--limit-per-company N]
"""

import argparse
import json
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_FILE = ROOT / "config" / "companies.yaml"
OUT_DIR = ROOT / "data" / "raw" / "transcripts"

DATASET = "Bose345/sp500_earnings_transcripts"
FILTER_URL = "https://datasets-server.huggingface.co/filter"
MAX_PAGE_LENGTH = 100  # API-imposed cap per request

# The dataset-viewer indexes a dataset lazily on first query and returns a
# transient "still loading" error in the meantime.
INDEX_LOADING_RETRY_SECONDS = 15
INDEX_LOADING_MAX_RETRIES = 20


def load_tickers() -> list[str]:
    companies = yaml.safe_load(COMPANIES_FILE.read_text())["companies"]
    return sorted({c["ticker"].upper() for c in companies})


def query_filter(where: str, offset: int, length: int) -> dict:
    params = {
        "dataset": DATASET,
        "config": "default",
        "split": "train",
        "where": where,
        "orderby": '"date" DESC',
        "offset": offset,
        "length": length,
    }
    for attempt in range(INDEX_LOADING_MAX_RETRIES):
        try:
            resp = requests.get(FILTER_URL, params=params, timeout=60)
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            print(f"    (connection issue: {exc.__class__.__name__}, retrying...)")
            time.sleep(INDEX_LOADING_RETRY_SECONDS)
            continue
        if "error" in data:
            transient = "loading" in data["error"] or "rebuilt" in data["error"]
            if transient:
                time.sleep(INDEX_LOADING_RETRY_SECONDS)
                continue
            raise RuntimeError(f"HF filter API error: {data['error']}")
        return data
    raise RuntimeError(f"HF filter API unreachable/loading after {INDEX_LOADING_MAX_RETRIES} attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker subset (default: all)")
    parser.add_argument("--limit-per-company", type=int, default=4, help="Most recent transcripts to keep per company")
    args = parser.parse_args()

    tickers = load_tickers()
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        tickers = [t for t in tickers if t in wanted]

    limit = min(args.limit_per_company, MAX_PAGE_LENGTH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_records = []

    for ticker in tickers:
        print(f"  {ticker}: querying...")
        data = query_filter(where=f"\"symbol\"='{ticker}'", offset=0, length=limit)
        rows = data["rows"]
        if not rows:
            print(f"    ! no transcripts found for {ticker} (likely not an S&P 500 constituent - see docs/dataset.md)")
            continue

        dest_dir = OUT_DIR / ticker
        dest_dir.mkdir(parents=True, exist_ok=True)
        for entry in rows:
            row = entry["row"]
            doc_id = f"{ticker}_{row['year']}Q{row['quarter']}"
            local_path = dest_dir / f"{doc_id}.json"
            local_path.write_text(json.dumps(row, indent=2), encoding="utf-8")

            record = {
                "doc_id": doc_id,
                "ticker": ticker,
                "filing_date": row["date"],
                "source": DATASET,
                "local_path": local_path.relative_to(ROOT).as_posix(),
            }
            manifest_records.append(record)
            print(f"    {doc_id} -> {record['local_path']}")

    manifest_path = OUT_DIR / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for record in manifest_records:
            f.write(json.dumps(record) + "\n")

    print(f"\nDone. {len(manifest_records)} transcripts recorded in {manifest_path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
