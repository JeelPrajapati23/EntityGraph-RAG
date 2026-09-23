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

This project shares its evaluation discipline with a sibling legal-RAG
project (ClauseIQ): provenance on every fact and checked, graph-derived eval
sets, with a different retrieval strategy (graph-guided hybrid retrieval
instead of pure vector search).

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

The engine was first built on SEC filings and earnings calls. That finance
pipeline was removed after the retarget, and it is in the git history.

## Try it

```bash
uv run python scripts/ask_depgraph.py "Is axios@0.21.1 exposed to CVE-2022-0155?"
uv run python scripts/ask_depgraph.py "How do I fix CVE-2024-45296 in express@4.17.1?"
```

Or serve the chat + graph demo page and HTTP API (`/query`,
`/graph/explore`, `/health`) at http://127.0.0.1:8000:

```bash
uv run reachfix
```

Both need the built data under `data/processed/depgraph/`. The build
scripts are listed in order in [`docs/dataset.md`](docs/dataset.md).

## Architecture

```
lockfiles (npm --before) ─┐
OSV advisories ───────────┼─► deterministic/derived edges ─┐
npm registry metadata ────┘                                ├─► graph (NetworkX) ─┐
advisory text ─► chunks ─► LLM exploit conditions ─────────┘                     │
advisory text ─► windowed embeddings ─► vector index ─────────────────────────┐  │
                                                                              ▼  ▼
query ──► router (semantic / relational / graph-guided hybrid) ──► retrieval + remediation plans
                                                                              │
                                              cited answer ([G#] graph facts, [A#] advisory text)
```

## Setup

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency and
environment management.

```bash
uv sync
```

Generation (exploit-condition extraction, router classification, answer
synthesis) runs on Groq (`openai/gpt-oss-120b`), and embeddings run on the
Hugging Face Inference API (`sentence-transformers/all-MiniLM-L6-v2`) —
copy `.env.example` to `.env` and set `GROQ_API_KEY` and `HF_TOKEN`.

## License

MIT — see [LICENSE](LICENSE).
