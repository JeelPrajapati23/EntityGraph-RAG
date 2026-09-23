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
