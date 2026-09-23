# Dataset notes

> The project was retargeted from SEC filings (schema v1, `config/companies.yaml`)
> to npm dependency/vulnerability exposure (schema v2, `config/projects.yaml`).
> The finance-era notes are in git history.

## Scope

- **Ecosystem:** npm only for the MVP. npm trees are denser and deeper than
  PyPI's, which suits a multi-hop demo. Cross-ecosystem support (and aliasing
  the same library across ecosystems) is a stated future improvement, not
  an MVP requirement.
- **Corpus:** 20 pinned root packages. See
  [`config/projects.yaml`](../config/projects.yaml). The mix covers large
  build tooling (react-scripts, @vue/cli-service, @angular/cli, next),
  mid-size test runners and servers, and a few small trees (axios,
  jsonwebtoken) where a vulnerable path can be checked by hand.

## Why pinned, date-bounded trees

A tree resolved today pulls the latest patched version of every transitive
dependency, so most historical vulnerabilities disappear from it. Each root
is instead resolved with `npm install --package-lock-only --before=<date>`,
using the day after the root's own release. This gives the tree a real
project would have installed then. The resolution is reproducible and
needs no custom resolver.

Spot checks done while choosing the corpus (2026-09-23):

| Root | Resolved transitive dep | Known advisory |
|---|---|---|
| `axios@0.21.1` | `follow-redirects@1.13.1` | CVE-2022-0155 (fixed 1.14.7) |
| `express@4.17.1` | `qs@6.7.0` | CVE-2022-24999 (fixed 6.7.3) |
| `express@4.17.1` | `path-to-regexp@0.1.7` | CVE-2024-45296 (fixed 0.1.10) |

`react-scripts@4.0.3` resolves to ~1,900 packages in ~70 s.

## Gotcha for Phase 1/2: lockfile nesting is not dependency depth

npm hoists packages, so in `package-lock.json` the `node_modules/…`
nesting is at most 2–3 levels even for deep trees. Logical `DEPENDS_ON`
edges have to be rebuilt from each entry's own `dependencies` map, using
Node's resolution rule: look in the nearest `node_modules` first, then walk
up. The path segments alone don't give the edges.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Dependency trees | `npm install --package-lock-only --before` | Deterministic. Produces `DEPENDS_ON` edges and declared ranges |
| Vulnerabilities | [OSV.dev](https://osv.dev) `/v1/querybatch` + `/v1/vulns/{id}` | Structured ranges plus free-text `details` for LLM extraction |
| Maintainers, license, publish time, deprecation | `registry.npmjs.org/<pkg>` | Maintainer emails are dropped and only usernames are kept |

Every fetched record goes into a `manifest.jsonl` with package, ecosystem,
version, source URL and fetch time, the same provenance discipline the
finance version used.

## Acquisition (Phase 1)

```bash
uv run python scripts/fetch_lockfiles.py     # → data/raw/lockfiles/<slug>/package-lock.json
uv run python scripts/fetch_osv.py           # → data/raw/osv/{vulns/<id>.json, package_vulns.jsonl}
uv run python scripts/fetch_npm_metadata.py  # → data/raw/npm/packuments/<name>.json
```

All three are incremental and write a `manifest.jsonl` next to their
output. Re-running only fetches what's new or changed (`--refresh` forces a
full fetch). The OSV and registry scripts read the lockfile manifest, so
run the lockfile script first.

**First full run (2026-09-23):**

| | |
|---|---|
| Lockfiles | 20 roots, 2–1,936 installed packages each |
| Unique package versions / names | 2,466 / 1,746 |
| Package versions with ≥1 advisory | 220 |
| Advisories | 296 (295 GHSA, 1 MAL). 285 have a CVE alias |
| Severity | 28 critical, 134 high, 106 moderate, 27 low, 1 unlabeled |
| Disk | lockfiles 2.9 MB, trimmed packuments 16 MB, advisories 2.1 MB |

Every root has at least one advisory in its tree. Counts range from 5
(`jsonwebtoken`) to 177 (`react-scripts`). For `axios@0.21.1` there are 24
advisories on axios itself and 5 on `follow-redirects@1.13.1`, the
transitive dependency the plan's example uses.

`package_vulns.jsonl` is OSV's own server-side matching of each package
version to advisories. It is **not** graph input: `HAS_VULNERABILITY` is
derived by our own semver matcher in Phase 3/4. It is kept as ground truth
to test that matcher against.

**Things found during the first run:**

- **Malicious-package advisories.** OSV includes OpenSSF `MAL-` records
  alongside GHSA ones. The one hit is `MAL-2023-462`: `fsevents` 1.x
  downloaded binaries from a storage bucket that was later taken over, and
  `fsevents@1.2.9` is in a corpus tree. MAL records have no GHSA severity
  label, and their `details` text is templated incident boilerplate rather
  than an exploit description, so Phase 3's condition extraction should
  skip them.
- **OSV `modified` precision differs by endpoint.** `/v1/querybatch` returns
  microseconds and `/v1/vulns/{id}` returns nanoseconds. The cache check
  compares at microsecond precision (`entitygraph_rag.npm.osv.normalize_modified`).
- **npm fetch timeout.** npm's default 5-minute fetch timeout let one stalled
  registry socket hang `browser-sync` for minutes. `fetch_lockfiles.py`
  passes `--fetch-timeout=60000 --fetch-retries=4`.

## Ingestion (Phase 2)

```bash
uv run python scripts/build_dependency_edges.py  # → data/processed/depgraph/{dependency_edges,unresolved_dependencies}.jsonl
uv run python scripts/build_advisory_chunks.py   # → data/processed/depgraph/advisory_chunks.jsonl
```

Both read the Phase 1 manifests and fully rewrite their output each run.
Outputs go under `data/processed/depgraph/` so they don't collide with the
finance pipeline's `data/processed/` files.

**Dependency edges** (`entitygraph_rag.npm.dependencies`). For each
dependency an installed package declares, the resolver finds the copy
Node would load: `<pkg>/node_modules/<dep>` first, then each enclosing
`node_modules` up to the top. Each edge carries:

- `version_range` (npm-alias prefix stripped) and the verbatim
  `declared_spec`
- `dependency_type`: prod / optional / peer
- `lockfile_doc_ids`, plus `occurrences`, which lists the install paths
  in every lockfile
- `registry_check` against the registry's declared dependencies for that
  version: match / range_differs / type_differs / not_declared /
  no_registry_data

The registry lists optional deps under both `dependencies` and
`optionalDependencies`, and a lockfile lists them only under the latter.
`registry.declared_dependencies` does the same split before the two are
compared.

**First run (2026-09-23):**

| | |
|---|---|
| Declared deps | 11,363 across 20 lockfiles, 11,328 resolved |
| Version-level edges | 5,983 (5,687 prod, 269 peer, 27 optional) |
| Registry cross-check | all 5,983 `match`. The registry declares no dep that a lockfile entry omits |
| Unresolved | 35, all peers: 27 marked optional in `peerDependenciesMeta`, and 8 required `react`/`react-dom` peers in the `next` tree (`--legacy-peer-deps` does not install peers) |
| Reachability | every installed package in every lockfile is reachable from its root |
| Advisory chunks | 383 from 295 advisories (55 split). Median 157 words. `MAL-2023-462` skipped |

**Gotcha: version-level edges can merge different install paths.** A
version installed at two paths can resolve the same dependency to two
different versions. The one case in the corpus is `http-errors@1.6.3` in
`browser-sync`, which gets `statuses@1.5.0` under `serve-index/` and
`statuses@1.4.0` under `send/`. Both edges are correct, but a version-level
traversal can combine them into a path no install actually has. Edges are
also merged across lockfiles, so traversals from one root should follow
only edges whose `lockfile_doc_ids` include that root's lockfile. Where
exact paths matter, `occurrences` has them.

**Advisory chunks** (`entitygraph_rag.npm.advisory`). `details` is
markdown. It is split into paragraphs at blank lines (never inside a
fenced code block), and the paragraphs are packed into chunks of at most
450 words. Packing runs across headings, and each heading stays glued to
the paragraph after it. The first attempt split at every heading instead,
which gave 1,026 chunks, many of them two-line "Patches" sections. Chunk
ids are `<osv_id>::<index>`, and each chunk carries `source_url` (the
osv.dev page), `aliases`, `summary`, `severity`, `modified`,
`affected_packages` and the `sections` it spans. A single block over 450
words (one 802-word PoC) is kept whole rather than cut.

## Extraction (Phase 3)

```bash
uv run python scripts/build_vulnerability_edges.py  # → data/processed/depgraph/vulnerability_edges.jsonl
uv run python scripts/extract_conditions.py [--limit N] [--ids GHSA-…]  # → exploit_conditions.jsonl (Groq)
```

**Deterministic and derived edges** (`entitygraph_rag.npm.vulnerabilities`,
`npm.versions`). `AFFECTS_VERSION_RANGE` and `FIXED_IN` come straight
from OSV's `affected` field, npm entries only. `HAS_VULNERABILITY` is
computed by our own matcher: OSV `SEMVER` events are evaluated per the
OSV spec, with `node-semver` (a Python port of npm's `semver`) doing the
comparisons. Withdrawn advisories get no `HAS_VULNERABILITY` edges.

| | |
|---|---|
| Edges | 328 `AFFECTS_VERSION_RANGE` (one per advisory and package, from 570 OSV `affected` entries), 551 `FIXED_IN` (26 fix targets are in some tree), 556 `HAS_VULNERABILITY` |
| vs OSV's own matches (`package_vulns.jsonl`) | 556 agree, 0 only ours, 0 only OSV's |
| `DEPENDS_ON` range check | 5,982 of 5,983 resolved versions satisfy their declared range. The one exception is a peer: `@pmmmwh/react-refresh-webpack-plugin` wants `type-fest@^0.13.1` and `--legacy-peer-deps` left 0.11.0 |

The range check is stored on each dependency edge as `range_satisfied`.

**LLM extraction of `EXPLOITABLE_WHEN`** (`entitygraph_rag.conditions`).
The prompt and output model are generated from the schema's `llm` edges
only. `ExploitCondition.category` has a closed vocabulary in
`schema/v2.yaml` (`property_values`), which becomes a `Literal` type. Each
condition must quote its `evidence` from the chunk. A quote that isn't
found in the chunk text or summary gets the condition dropped. The match
ignores case, whitespace and markdown punctuation, and quotes of 6+ words
may match fuzzily at ≥95. Each edge records `evidence_match: exact|fuzzy`.

Prompt revisions, from a 9-advisory sample (one revision only, to avoid
tuning the prompt to a small set):

- Conditions must describe the victim application or its environment,
  never an attacker's step. The first version returned things like "the
  attack payload is placed in the query string".
- PoC code shows attacker steps. The first version pulled
  "conditions" out of axios PoC code.
- The evidence check originally failed on markdown link brackets and on a
  dropped "the", which lost two true conditions.

**Full run (2026-09-23):** all 383 chunks, spread over 8 rotated Groq
keys (see `llm_client.RotatingGroq`). The free tier's 200K tokens/day per
key covers ~73 chunks, at ~2.3K tokens each.

| | |
|---|---|
| Conditions | 637 on 263 of 295 advisories. 32 advisories state no precondition |
| Evidence | 631 exact matches, 6 fuzzy, 15 dropped as not found in the text |
| Category | 279 `input_source`, 145 `configuration`, 104 `api_usage`, 59 `other`, 50 `platform` |

Spot checks look right on the whole: "the application extracts
attacker-controlled tar archives", "the application calls `setIn` with
data derived from a request". There's some noise too, e.g. "express must
not redirect before the template appears". There's no labeled set yet to
measure precision. That belongs to the evaluation phase. Re-running
resumes from the cache (`.cache/conditions/`, keyed on prompt + chunk +
model + schema version).

## Resolution (Phase 4)

```bash
uv run python scripts/resolve_nodes.py  # → nodes.jsonl, registry_edges.jsonl, condition_edges.jsonl
```

npm names and versions are already canonical, so this phase gives every
node one id and checks that every edge endpoint resolves to one
(`entitygraph_rag.npm.nodes`).

- **Ids.** `npm:<name>` for a Package, `npm:<name>@<version>` for a
  PackageVersion, the OSV id for a Vulnerability, `npm-user:<username>`,
  `license:<id>`, and `<osv_id>::cond::<n>` for an ExploitCondition.
- **PackageVersion** covers every tree version plus every `FIXED_IN`
  target (`in_tree: false`), with `is_root`, `published_at`,
  `deprecated` and `lockfile_doc_ids`.
- **Registry edges:** `VERSION_OF`, `MAINTAINED_BY` (current maintainers
  only; the registry keeps no history) and `LICENSED_UNDER`. An SPDX
  expression like `(MIT OR CC0-1.0)` gives one edge per license, each
  carrying the full expression and operator. Two legacy spellings are
  mapped (`Apache 2.0`, `AFLv2.1`). `BSD` names no single SPDX license
  and is kept as is rather than guessed.
- **ExploitCondition nodes** merge near-duplicate conditions within one
  advisory (token_sort_ratio ≥ 90), since multi-chunk advisories restate
  them. Conditions are never merged across advisories.

**First run (2026-09-23):** 6,460 nodes (1,765 Package, 2,905
PackageVersion, 296 Vulnerability, 844 Maintainer, 19 License, 631
ExploitCondition merged from 637 extracted conditions). 17,944 edges, 0
dangling endpoints. 122 tree versions are deprecated.

**Gotcha: one CVE can belong to several advisories.** Six CVE ids are
aliases of two advisories each, for example `CVE-2024-45296` on
`GHSA-9wv6-86v2-598j` and `GHSA-37ch-88jc-xwx2` (path-to-regexp). These
are an advisory and its incomplete-fix follow-up. They list each other
as aliases but have different ranges: 0.1.x is "fixed" in 0.1.10 by one
and in 0.1.13 by the other. They stay separate nodes, because a merged
node would have an ambiguous `FIXED_IN`. `NodeLookup` resolves a CVE to
every advisory that lists it, and Phase 9 remediation must take the
highest fix across all of them.

**Query-time lookup** (`entitygraph_rag.npm.lookup.NodeLookup`). An
advisory id resolves to itself. A CVE resolves to every advisory aliasing
it. `name@version` resolves to that PackageVersion. A package name
matches case-insensitively, then fuzzily with `-_./` treated alike
(`follow redirects` → `follow-redirects`). The finance-era
`normalize_name` is not reused: it drops words like "co" and "group",
which are real npm package names.

## Graph construction (Phase 5)

```bash
uv run python scripts/build_depgraph.py  # → data/processed/depgraph/graph.pkl
```

The finance-era `GraphStore` interface and `NetworkXGraphStore` are
reused. `upsert_edge` was generalized, and finance edges load exactly as
before:
- provenance fields are optional, and `confidence` defaults to 1.0 for
  deterministic and derived edges
- an edge can bring a `provenance` list and a `properties` dict

`entitygraph_rag.npm.graph_load` maps DepGraph rows onto that shape. A
`DEPENDS_ON` edge's provenance lists every lockfile it occurs in, plus the
registry packument when `registry_check` is `match`. That is the plan's
"one fact from a lockfile and a registry cross-check, both kept as
provenance". A merged `EXPLOITABLE_WHEN` edge keeps one provenance entry
per source chunk, with its evidence quote.

**Edge collision fixed at the source.** OSV lists a package once per
release line (`minimatch` has 8 `affected` entries in one advisory).
These now become one `AFFECTS_VERSION_RANGE` edge per (advisory, package)
carrying all the ranges. Before, they would have silently merged in the
store, keeping only the first entry's ranges.

**Traversal** (`entitygraph_rag.graph.exposure`, written against
`GraphStore` only):
- `dependency_paths` does a breadth-first walk over `DEPENDS_ON`,
  following only edges whose `lockfile_doc_ids` include the chosen
  lockfile.
- `exposure` returns every reachable (vulnerable version, advisory) with
  its shortest path.
- `exposed_lockfiles` lists the projects affected by one advisory.

**First build (2026-09-23):** 6,460 nodes, 17,944 edges.

- **Reachability:** for all 20 lockfiles, a lockfile-scoped walk from the
  root reaches exactly the versions that lockfile installs. The check
  reads the raw lockfiles, independently of the graph.
- **Exposure:** per-root advisory counts match Phase 1 (177 for
  react-scripts, 5 for jsonwebtoken).
- **Depth:** trees go deeper than the plan's "4–6 levels". Max depth is
  3–11 hops, and the deepest vulnerable version is 9 hops from its root
  (`json-schema@0.2.3` under react-scripts, `ansi-regex@3.0.0` under
  @angular/cli).
- **Demo path:** `npm:axios@0.21.1 -> depends_on ->
  npm:follow-redirects@1.13.1 [VULNERABLE: GHSA-74fj-2j2h-c42q /
  CVE-2022-0155]`.

## Schema

See [`schema/v2.yaml`](../schema/v2.yaml). Key decisions:

- **Two-level package identity** (`Package` name vs. `PackageVersion`),
  like deps.dev and GUAC. Trees and exposure are about versions.
  Maintainers and advisory ranges are about names.
- **Each edge type declares its extraction method.** Only
  `EXPLOITABLE_WHEN` (advisory text → `ExploitCondition`) is LLM-extracted.
  `HAS_VULNERABILITY` is *derived* by semver-matching tree versions
  against OSV ranges. Everything else is deterministic ground truth.
- **`DEPENDS_ON` keeps the declared range**, not only the resolved
  version. Phase 9 remediation needs it to check whether a fixed version
  satisfies every dependent's constraint.
- **CVE ids are aliases.** npm advisories are keyed by GHSA id, so a query
  naming a CVE resolves through `Vulnerability.aliases`.
