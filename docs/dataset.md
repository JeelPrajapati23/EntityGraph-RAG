# Dataset notes

## Company universe

20 companies across two linked groups — see [`config/companies.yaml`](../config/companies.yaml):

- **Semiconductor suppliers/fabs (10):** NVIDIA, TSMC, Intel, AMD, Qualcomm,
  Texas Instruments, Broadcom, Micron, ASML, STMicroelectronics
- **Automotive/consumer-electronics customers (10):** Apple, Tesla, Ford,
  General Motors, Alphabet, Sony, Dell, HP, Cisco, Amazon

Chosen as a single sector pairing (not 20 unrelated companies) because real
`SUPPLIES` / `COMPETES_WITH` / `EXECUTIVE_OF` edges already exist between
them — e.g. TSMC fabricates chips for NVIDIA, AMD, and Apple; Qualcomm
supplies modems to Apple; NVIDIA and Intel/AMD/Qualcomm compete directly.
That density is what makes multi-hop questions ("who fabricates chips for
both NVIDIA and Apple?") answerable and gives the eventual golden-set
questions something non-trivial to traverse.

## Filing types & a schema nuance

The default filing set is 10-K / 10-Q / 8-K. Three companies here are
**foreign private issuers** (TSMC, ASML, STMicroelectronics) plus one more
(Sony) — they file **20-F** (annual, in place of 10-K) and **6-K** (in place
of 8-K/10-Q) instead. Tracked via the `filer_type` field in
`config/companies.yaml` so the EDGAR downloader can branch on it per company
rather than assuming one filing-type set for all 20.

## Data acquisition

Two scripts pull the raw corpus into `data/raw/` (gitignored — acquired
data, not source):

- **`scripts/fetch_edgar_filings.py`** — resolves CIKs from EDGAR's
  `company_tickers.json`, then pulls each company's most recent filings via
  `data.sec.gov/submissions/`, branching on `filer_type` per company. Sends
  a descriptive `User-Agent` with a contact email, per SEC's fair-access
  policy, and rate-limits itself well under SEC's 10 req/sec cap.
- **`scripts/fetch_transcripts.py`** — pulls earnings-call transcripts from
  **`Bose345/sp500_earnings_transcripts`** on Hugging Face (MIT licensed,
  "research and educational use," speaker-segmented, 2005-2025). Queries
  the dataset-viewer's `/filter` API server-side (rather than downloading
  the ~1GB parquet file) so only matching rows cross the wire.

Both write a `manifest.jsonl` alongside the downloaded files — `doc_id`,
`ticker`/`cik`, `filing_date`/date, `source_url`/`source`, `local_path` —
which is what the ingestion pipeline will read to build chunk provenance.

**Coverage gap:** the transcript dataset only covers S&P 500 constituents,
so TSM/ASML/STM (foreign private issuers, not S&P 500 members) have no
transcripts — filings-only for those three.

**Caveat worth naming:** transcript text carries each company's own
copyright/reproduction notice (e.g. "The content of today's call is
NVIDIA's property..."). The dataset's MIT license covers the uploader's
compilation, not necessarily the underlying call content. Fine for
research/educational, non-redistributed use here — flagged so it's a
documented, deliberate choice rather than an oversight.

## Schema

See [`schema/v1.yaml`](../schema/v1.yaml) for the fixed node/edge type
vocabulary. Kept separate from company selection: swapping in a different
company universe (or a different domain's schema entirely — see the
project README) shouldn't require touching this file.
