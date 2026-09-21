# EntityGraph-RAG

A hybrid retrieval engine that combines vector search with graph traversal for
multi-hop question answering over document collections.

Demonstrated here on public SEC filings and earnings call transcripts, but the
extraction schema and retrieval router are domain-agnostic — see
[`docs/adapting-to-a-new-domain.md`](docs/adapting-to-a-new-domain.md) (coming
in a later phase) for notes on retargeting the pipeline to a different corpus
(e.g. legal contracts, supply-chain docs, research papers).

This project shares ingestion and evaluation philosophy with a sibling
legal-RAG project (ClauseIQ) — same discipline around chunking, provenance,
and golden-set evaluation, different retrieval strategy (graph-guided hybrid
retrieval instead of pure vector search).

## Status

Early scaffolding. Follow along in the commit history — this project is being
built incrementally, phase by phase:

- [x] Phase 0 — Dataset & schema design
- [ ] Phase 1 — Ingestion pipeline
- [ ] Phase 2 — Entity & relation extraction
- [ ] Phase 3 — Graph construction & storage
- [ ] Phase 4 — Hybrid retrieval router
- [ ] Phase 5 — Answer synthesis & citations
- [ ] Phase 6 — Evaluation framework
- [ ] Phase 7 — API layer & deployment
- [ ] Phase 8 — MCP server exposure (stretch)

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

## License

MIT — see [LICENSE](LICENSE).
