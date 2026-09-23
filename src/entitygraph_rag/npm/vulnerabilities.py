"""Build the advisory edges of schema v2 from OSV records.

- AFFECTS_VERSION_RANGE (deterministic): advisory -> Package, carrying the
  OSV `ranges` verbatim, merged across every `affected` entry for that package.
- FIXED_IN (deterministic): advisory -> PackageVersion for each `fixed`
  event. The fixed version may be in no corpus tree (`in_tree` false).
- HAS_VULNERABILITY (derived): corpus PackageVersion -> advisory, by our own
  range matching (npm.versions), never read from OSV's match results.
  Withdrawn advisories get no HAS_VULNERABILITY edges.

Node ids follow schema/v2.yaml: "npm:<name>" for a Package,
"npm:<name>@<version>" for a PackageVersion, the OSV id for a Vulnerability.
"""

from collections import defaultdict

from .versions import fixed_versions, is_affected

ECOSYSTEM = "npm"
OSV_WEB = "https://osv.dev/vulnerability/"


def package_id(name: str) -> str:
    return f"{ECOSYSTEM}:{name}"


def version_id(name: str, version: str) -> str:
    return f"{ECOSYSTEM}:{name}@{version}"


def npm_affected(record: dict) -> list[dict]:
    """The record's `affected` entries for npm packages (advisories can also list other ecosystems)."""
    return [a for a in record.get("affected", []) if a.get("package", {}).get("ecosystem") == ECOSYSTEM]


def build_vulnerability_edges(
    advisories: list[dict], corpus: dict[tuple[str, str], set[str]]
) -> list[dict]:
    """`corpus` maps (name, version) -> doc_ids of the lockfiles it is installed in."""
    versions_of: dict[str, set[str]] = defaultdict(set)
    for name, version in corpus:
        versions_of[name].add(version)

    rows = []
    for record in advisories:
        osv_id = record["id"]
        provenance = {"source_doc_id": osv_id, "source_url": OSV_WEB + osv_id}
        affected_versions: dict[tuple[str, str], None] = {}  # ordered set
        affects: dict[str, dict] = {}
        for entry in npm_affected(record):
            name = entry["package"]["name"]
            # OSV often lists one package in several entries, one per release line.
            # They become one edge per (advisory, package) carrying every range.
            if name not in affects:
                affects[name] = {
                    "relation": "AFFECTS_VERSION_RANGE", "extraction_method": "deterministic",
                    "subject": osv_id, "object": package_id(name), "ranges": [], "versions": [],
                    **provenance,
                }
                rows.append(affects[name])
            affects[name]["ranges"].extend(entry.get("ranges", []))
            affects[name]["versions"].extend(entry.get("versions", []))
            for fixed in fixed_versions(entry):
                rows.append({
                    "relation": "FIXED_IN", "extraction_method": "deterministic",
                    "subject": osv_id, "object": version_id(name, fixed),
                    "object_name": name, "object_version": fixed, "in_tree": (name, fixed) in corpus,
                    **provenance,
                })
            for version in sorted(versions_of.get(name, ())):
                if is_affected(version, entry):
                    affected_versions[(name, version)] = None

        if record.get("withdrawn"):
            continue
        for name, version in affected_versions:
            rows.append({
                "relation": "HAS_VULNERABILITY", "extraction_method": "derived",
                "subject": version_id(name, version), "object": osv_id,
                "subject_name": name, "subject_version": version,
                "lockfile_doc_ids": sorted(corpus[(name, version)]),
                **provenance,
            })
    return rows


def compare_with_osv(rows: list[dict], osv_matches: list[dict]) -> dict:
    """Check derived HAS_VULNERABILITY edges against OSV's own server-side matches.

    `osv_matches` is package_vulns.jsonl: {name, version, vuln_ids}. Returns
    counts plus the differing (name, version, vuln_id) triples.
    """
    ours = {(r["subject_name"], r["subject_version"], r["object"]) for r in rows if r["relation"] == "HAS_VULNERABILITY"}
    theirs = {(m["name"], m["version"], vid) for m in osv_matches for vid in m["vuln_ids"]}
    return {
        "agree": len(ours & theirs),
        "only_ours": sorted(ours - theirs),
        "only_osv": sorted(theirs - ours),
    }
