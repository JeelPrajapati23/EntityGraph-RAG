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
