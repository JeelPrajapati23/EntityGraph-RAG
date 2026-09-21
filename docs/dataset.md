# Dataset notes (Phase 0)

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
both NVIDIA and Apple?") answerable and gives Phase 6's golden-set questions
something non-trivial to traverse.

## Filing types & a schema nuance

The plan's default is 10-K / 10-Q / 8-K. Three companies here are **foreign
private issuers** (TSMC, ASML, STMicroelectronics) plus one more (Sony) —
they file **20-F** (annual, in place of 10-K) and **6-K** (in place of
8-K/10-Q) instead. Tracked via the `filer_type` field in
`config/companies.yaml` so the Phase 1 EDGAR downloader can branch on it
per company rather than assuming one filing-type set for all 20.

## Still open (resolved in Phase 1, not blocking the schema)

- **CIK numbers** — resolved at ingestion time from EDGAR's
  `company_tickers.json` rather than hardcoded, so the config file doesn't
  go stale.
- **Earnings-call transcript source** — plan suggests a public
  Hugging Face/Kaggle dataset or a small scraped sample; source will be
  picked and documented when the ingestion pipeline is built (Phase 1),
  with terms-of-use checked before anything is committed/distributed.

## Schema

See [`schema/v1.yaml`](../schema/v1.yaml) for the fixed node/edge type
vocabulary. Kept separate from company selection: swapping in a different
company universe (or a different domain's schema entirely — see the
project README) shouldn't require touching this file.
