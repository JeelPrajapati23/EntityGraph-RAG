# EntityGraph-RAG

A hybrid retrieval engine that combines vector search with graph traversal for
multi-hop question answering over document collections.

Demonstrated here on public SEC filings and earnings call transcripts, but the
extraction schema and retrieval router are domain-agnostic — see
[`docs/adapting-to-a-new-domain.md`](docs/adapting-to-a-new-domain.md) (coming
soon) for notes on retargeting the pipeline to a different corpus (e.g. legal
contracts, supply-chain docs, research papers).

This project shares ingestion and evaluation philosophy with a sibling
legal-RAG project (ClauseIQ) — same discipline around chunking, provenance,
and golden-set evaluation, different retrieval strategy (graph-guided hybrid
retrieval instead of pure vector search).

## Status

Active development — dataset, schema, data acquisition, ingestion/chunking,
entity/relation extraction, and entity resolution are in place; graph
construction, the hybrid retrieval router, and evaluation are next. Follow
along in the commit history.

## Architecture (evolving)

```
documents → ingestion/chunking → entity & relation extraction → knowledge graph
                                                                       │
query ──► router (semantic / relational / graph-guided hybrid) ◄──────┘
                                │
                    retrieval (vector / graph / both)
                                │
                    answer synthesis + citations (text + graph path)
```

## Setup

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency and
environment management.

```bash
uv sync
```

Extraction (`scripts/extract_triples.py`) calls the Gemini API — copy
`.env.example` to `.env` and set `GEMINI_API_KEY`.

## License

MIT — see [LICENSE](LICENSE).
