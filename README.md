# reachfix

Which of your projects does a vulnerability reach, through which chain of
transitive dependencies, and what is the smallest upgrade that fixes it
without breaking the version ranges your other dependencies declare?

reachfix combines a dependency/vulnerability knowledge graph with semantic
search over advisory text. It answers multi-hop supply-chain questions
that plain similarity search can't reach, e.g. "is react-scripts@4.0.3
exposed to CVE-2022-0155, and through which chain?" or "what should mocha
8.4.0 upgrade to so it stops pulling in a vulnerable minimatch?"

The graph is mostly deterministic: dependency edges come from npm lockfiles,
and vulnerability ranges come from OSV.dev's structured data. The LLM
handles two narrow, checkable jobs: extracting exploitability conditions
from advisory free text, and writing answers that cite the graph facts and
advisory text they rest on. See [`docs/dataset.md`](docs/dataset.md) and
[`schema/v2.yaml`](schema/v2.yaml).

This project shares ingestion and evaluation philosophy with a sibling
legal-RAG project (ClauseIQ) — same discipline around chunking, provenance,
and golden-set evaluation, different retrieval strategy (graph-guided hybrid
retrieval instead of pure vector search).

## Status

The npm pipeline ("DepGraph") runs end to end over 20 date-pinned projects
(2,466 package versions, 296 OSV advisories):

- **Acquisition and graph:** lockfiles resolved with `npm install --before`,
  OSV advisories, npm registry metadata. Version-level `DEPENDS_ON` edges
  are rebuilt with Node's resolution rule. `HAS_VULNERABILITY` edges come
  from our own semver matching, which agrees with OSV's own matching
  556/556.
- **Retrieval:** a router classifies each question as semantic, relational
  (exposure, affected projects, dependency path, remediation, neighbors) or
  graph-guided hybrid. Advisory text is searched with windowed MiniLM
  embeddings.
- **Remediation:** for each vulnerable copy, the lowest fixed version that
  every dependent's declared range accepts. If a dependent blocks it, the
  upgrade that dependent needs, repeating up to the project itself, with an
  npm `overrides` fallback.
- **Answers:** cite `[G#]` graph facts (readable dependency chains) and
  `[A#]` advisory text with osv.dev links. They are checked for advisory
  ids and package versions that aren't in the evidence.

The engine was first built on SEC filings (schema v1). That finance
pipeline is still in the repo and is being removed.

## Try it

```bash
uv run python scripts/ask_depgraph.py "Is axios@0.21.1 exposed to CVE-2022-0155?"
uv run python scripts/ask_depgraph.py "How do I fix CVE-2024-45296 in express@4.17.1?"
```

The build scripts that produce `data/` are listed in order in
[`docs/dataset.md`](docs/dataset.md).

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
