"""Fetch primary filing documents for the configured company universe from SEC EDGAR.

Uses SEC's official JSON APIs (company_tickers.json for CIK lookup,
data.sec.gov/submissions for the filing index) rather than a third-party
downloader, and branches per company on `filer_type` from
config/companies.yaml — domestic filers get 10-K/10-Q/8-K, foreign private
issuers get 20-F/6-K instead (see docs/dataset.md).

Downloaded documents and a provenance manifest are written to
data/raw/filings/ (gitignored — this is acquired data, not source).

Usage:
    uv run python scripts/fetch_edgar_filings.py [--max-per-form N] [--tickers NVDA,AAPL]
"""

import argparse
import json
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_FILE = ROOT / "config" / "companies.yaml"
OUT_DIR = ROOT / "data" / "raw" / "filings"

# SEC's fair-access policy requires a descriptive User-Agent with contact info:
# https://www.sec.gov/os/webmaster-faq#developers
SEC_CONTACT_EMAIL = "jeet.a.daiya24@gmail.com"
HEADERS = {"User-Agent": f"EntityGraph-RAG research project ({SEC_CONTACT_EMAIL})"}

TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"

FORMS_BY_FILER_TYPE = {
    "domestic": {"10-K", "10-Q", "8-K"},
    "foreign_private_issuer": {"20-F", "6-K"},
}

# SEC's documented limit is 10 requests/second; stay comfortably under it.
REQUEST_DELAY_SECONDS = 0.15


def load_companies() -> list[dict]:
    return yaml.safe_load(COMPANIES_FILE.read_text())["companies"]


def load_ticker_cik_map() -> dict[str, int]:
    resp = requests.get(TICKER_CIK_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return {row["ticker"].upper(): row["cik_str"] for row in resp.json().values()}


def fetch_submissions(cik: int) -> dict:
    resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp.json()


def select_recent_filings(submissions: dict, wanted_forms: set[str], max_per_form: int) -> list[dict]:
    recent = submissions["filings"]["recent"]
    counts: dict[str, int] = {}
    selected = []
    for i, form in enumerate(recent["form"]):
        if form not in wanted_forms or counts.get(form, 0) >= max_per_form:
            continue
        selected.append(
            {
                "form": form,
                "accessionNumber": recent["accessionNumber"][i],
                "primaryDocument": recent["primaryDocument"][i],
                "filingDate": recent["filingDate"][i],
            }
        )
        counts[form] = counts.get(form, 0) + 1
    return selected


def download_filing(cik: int, filing: dict, ticker: str, dest_dir: Path) -> dict:
    accession_nodash = filing["accessionNumber"].replace("-", "")
    url = ARCHIVE_URL.format(cik=cik, accession_nodash=accession_nodash, doc=filing["primaryDocument"])
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)

    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filing["primaryDocument"]).suffix or ".html"
    local_path = dest_dir / f"{filing['accessionNumber']}_{filing['form']}{ext}"
    local_path.write_bytes(resp.content)

    return {
        "doc_id": filing["accessionNumber"],
        "ticker": ticker,
        "cik": cik,
        "form": filing["form"],
        "filing_date": filing["filingDate"],
        "source_url": url,
        "local_path": local_path.relative_to(ROOT).as_posix(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-per-form", type=int, default=2, help="Max filings to keep per form type per company")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker subset (default: all)")
    args = parser.parse_args()

    companies = load_companies()
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        companies = [c for c in companies if c["ticker"].upper() in wanted]

    print(f"Resolving CIKs for {len(companies)} companies...")
    ticker_cik = load_ticker_cik_map()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_records = []

    for company in companies:
        ticker = company["ticker"]
        cik = ticker_cik.get(ticker.upper())
        if cik is None:
            print(f"  ! {ticker}: no CIK found in EDGAR ticker map, skipping")
            continue

        wanted_forms = FORMS_BY_FILER_TYPE[company["filer_type"]]
        print(f"  {ticker} (CIK {cik}): fetching submissions...")
        submissions = fetch_submissions(cik)
        filings = select_recent_filings(submissions, wanted_forms, args.max_per_form)
        print(f"    {len(filings)} filings selected ({', '.join(sorted(wanted_forms))})")

        dest_dir = OUT_DIR / ticker
        for filing in filings:
            record = download_filing(cik, filing, ticker, dest_dir)
            manifest_records.append(record)
            print(f"    downloaded {record['form']} {record['filing_date']} -> {record['local_path']}")

    manifest_path = OUT_DIR / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for record in manifest_records:
            f.write(json.dumps(record) + "\n")

    print(f"\nDone. {len(manifest_records)} documents recorded in {manifest_path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
