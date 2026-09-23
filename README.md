# EntityGraph-RAG

A hybrid retrieval engine combining a dependency/vulnerability knowledge graph
with semantic search over advisory text. It answers multi-hop supply-chain
exposure questions that plain similarity search can't reach, such as "is
react-scripts@4.0.3 exposed to CVE-2022-0155, and through which chain of
transitive dependencies?"

The graph is mostly deterministic: dependency edges come from npm lockfiles,
and vulnerability ranges come from OSV.dev's structured data. The LLM
handles one narrow, checkable job: extracting exploitability conditions from
advisory free text. See [`docs/dataset.md`](docs/dataset.md) and
[`schema/v2.yaml`](schema/v2.yaml).

> **Retargeting in progress.** This engine was first built and run end to
> end on SEC filings (schema v1). It is now being retargeted to npm
> dependency graphs (schema v2). The graph store, retrieval, router,
> synthesis, evaluation and API layers carry over. Acquisition, ingestion,
> extraction and resolution are being rewritten.

This project shares ingestion and evaluation philosophy with a sibling
legal-RAG project (ClauseIQ) — same discipline around chunking, provenance,
and golden-set evaluation, different retrieval strategy (graph-guided hybrid
retrieval instead of pure vector search).

## Status

DepGraph Phase 0 (schema v2 and corpus scope) is done. For the finance
version, the full pipeline from raw documents through a cited,
natural-language answer is in place: dataset, schema, data acquisition,
ingestion/chunking, entity/relation extraction, entity resolution, graph
construction (NetworkX, behind a swappable GraphStore interface), semantic
(vector) retrieval, a router that classifies each query as semantic /
relational / graph-guided-hybrid, answer synthesis with a structured
citation block (chunk snippets + readable graph paths), and an evaluation
framework (golden-set, graph-path precision/recall, router accuracy,
LLM-judged answer quality). Follow along in the commit history.

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

Generation (extraction, router classification, answer synthesis, eval
judging) runs on Groq (`openai/gpt-oss-120b`), and embeddings run on the
Hugging Face Inference API (`sentence-transformers/all-MiniLM-L6-v2`) —
copy `.env.example` to `.env` and set `GROQ_API_KEY` and `HF_TOKEN`.

## License

MIT — see [LICENSE](LICENSE).
