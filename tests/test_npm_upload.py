import pytest

from reachfix.depgraph import DepGraphContext
from reachfix.depgraph.scan import run_scan
from reachfix.graph import NetworkXGraphStore, OverlayGraphStore
from reachfix.graph.exposure import exposure
from reachfix.npm.graph_load import to_entity
from reachfix.npm.releases import Releases
from reachfix.npm.upload import load_upload

# Base (corpus) graph: advisory GHSA-a (CVE-1, HIGH) affects lib < 1.0.2. Only lib@1.0.0 is a corpus version.
BASE_NODES = [
    {"node_id": "npm:lib", "node_type": "Package", "name": "lib", "aliases": ["lib"], "properties": {}},
    {"node_id": "npm:lib@1.0.0", "node_type": "PackageVersion", "name": "lib@1.0.0", "aliases": ["lib@1.0.0"],
     "properties": {"in_tree": True}},
    {"node_id": "GHSA-a", "node_type": "Vulnerability", "name": "GHSA-a", "aliases": ["GHSA-a", "CVE-1"],
     "properties": {"aliases": ["CVE-1"], "severity": "HIGH", "summary": "lib is bad"}},
]
BASE_EDGES = [
    {"subject_id": "GHSA-a", "relation": "AFFECTS_VERSION_RANGE", "object_id": "npm:lib", "source_doc_id": "GHSA-a",
     "properties": {"ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.0.2"}]}], "versions": []}},
    {"subject_id": "npm:lib@1.0.0", "relation": "HAS_VULNERABILITY", "object_id": "GHSA-a", "source_doc_id": "GHSA-a",
     "properties": {"lockfile_doc_ids": ["lockfile:npm:other@1.0.0"]}},
    {"subject_id": "GHSA-a", "relation": "FIXED_IN", "object_id": "npm:lib@1.0.2", "source_doc_id": "GHSA-a",
     "properties": {}},
]


def base_store():
    store = NetworkXGraphStore()
    store.load([to_entity(n) for n in BASE_NODES], BASE_EDGES)
    return store


def lockfile(root_lib="1.0.0", mid_lib="^1.0.0"):
    """app@1.0.0 -> mid@1.0.0 -> lib@1.0.0, app -(dev)-> lib@1.0.0, app -(dev)-> tool@2.0.0 (dev-only)."""
    return {"name": "app", "lockfileVersion": 3, "packages": {
        "": {"name": "app", "version": "1.0.0", "dependencies": {"mid": "^1.0.0"},
             "devDependencies": {"lib": root_lib, "tool": "^2.0.0"}},
        "node_modules/mid": {"version": "1.0.0", "dependencies": {"lib": mid_lib}},
        "node_modules/lib": {"version": "1.0.0"},
        "node_modules/tool": {"version": "2.0.0", "dev": True},
    }}


def releases(lib_versions=("1.0.0", "1.0.1", "1.0.2", "1.0.3")):
    def package(manifests):
        return {"versions": list(manifests), "complete": True,
                "manifests": {v: {"dependencies": d, "deprecated": None} for v, d in manifests.items()}}
    return Releases({"lib": package({v: {} for v in lib_versions}), "mid": package({"1.0.0": {"lib": "^1.0.0"}})})


def context(store, rel=None):
    return DepGraphContext(store=store, lookup=None, index=None, chunks_by_id={}, embedding_client=None, releases=rel)


def test_upload_edges_and_coverage():
    base = base_store()
    upload = load_upload(base, lockfile())

    assert upload.root_id == "project:app@1.0.0" and upload.lockfile_doc_id.startswith("lockfile:upload:")
    hits = exposure(upload.store, upload.root_id, upload.lockfile_doc_id)
    # One HAS_VULNERABILITY edge despite the base having one too: the overlay's replaces it.
    assert [(h["version_id"], h["vulnerability_id"], h["path"]) for h in hits] == [
        ("npm:lib@1.0.0", "GHSA-a", ["project:app@1.0.0", "npm:lib@1.0.0"])]
    assert upload.unchecked == ["mid@1.0.0", "tool@2.0.0"]
    assert upload.dev_only == {"npm:tool@2.0.0"}
    # The base graph is untouched.
    assert (base.node_count(), base.edge_count()) == (4, 3)


def test_overlay_entity_falls_back_to_base_over_implicit_nodes():
    upload = load_upload(base_store(), lockfile())
    # The overlay's HAS_VULNERABILITY edge creates a bare GHSA-a node in the overlay; the base's attributes win.
    assert upload.store.get_entity("GHSA-a")["properties"]["severity"] == "HIGH"
    assert upload.store.get_entity("npm:mid@1.0.0")["properties"]["uploaded"] is True


def test_overlay_neighbors_merge_layers():
    base = base_store()
    store = OverlayGraphStore(base)
    store.upsert_edge({"subject_id": "npm:lib@1.0.0", "relation": "HAS_VULNERABILITY", "object_id": "GHSA-b",
                       "source_doc_id": "GHSA-b"})
    assert sorted(e["entity_id"] for e in store.neighbors("npm:lib@1.0.0", relation="HAS_VULNERABILITY")) == [
        "GHSA-a", "GHSA-b"]
    assert base.neighbors("npm:lib@1.0.0", relation="HAS_VULNERABILITY")[0]["entity_id"] == "GHSA-a"


def test_scan_edits_the_projects_own_range():
    store = base_store()
    result = run_scan(context(store, releases()), load_upload(store, lockfile()))

    assert result["totals"]["advisories"] == 1 and result["totals"]["by_severity"] == {"HIGH": 1}
    assert result["results"][0]["severity"] == "HIGH" and result["results"][0]["dev_only"] is False
    [row] = result["remediation"]["results"]
    # The root pins lib "1.0.0" in devDependencies; mid's "^1.0.0" already admits the fix.
    assert row["plan"]["status"] == "blocked" and row["resolved"] and not row["incomplete"]
    [root_dep] = [d for d in row["plan"]["dependents"] if d["dependent"] == "project:app@1.0.0"]
    assert root_dep["upgrade"] == {"version_id": "project:app@1.0.0", "dep_name": "lib", "current_range": "1.0.0",
                                   "dependency_type": "dev", "status": "edit_manifest", "target_version": "1.0.2",
                                   "suggested_range": "^1.0.2"}
    assert any('lib "1.0.0" -> "^1.0.2"' in step for step in row["actions"])


def test_scan_in_range_and_no_fix():
    store = base_store()
    result = run_scan(context(store, releases()), load_upload(store, lockfile(root_lib="^1.0.0")))
    assert result["remediation"]["results"][0]["plan"]["status"] == "in_range"

    result = run_scan(context(store, releases(lib_versions=("1.0.0", "1.0.1"))), load_upload(store, lockfile()))
    [row] = result["remediation"]["results"]
    assert row["plan"]["status"] == "no_fix" and not row["resolved"]
    assert any("the project declares lib" in step and "remove or replace it" in step for step in row["actions"])


def test_scan_flags_missing_release_metadata():
    store = base_store()
    result = run_scan(context(store, Releases({})), load_upload(store, lockfile()))
    [row] = result["remediation"]["results"]
    # No version list for lib itself: no plan, just the advisories' own fixed versions.
    assert row["plan"]["status"] == "no_metadata" and row["incomplete"] == ["lib"] and not row["resolved"]
    assert "no upgrade plan" in row["actions"][0] and "1.0.2" in row["actions"][0]
    assert any("release metadata missing" in w for w in result["warnings"])

    # lib is known but mid, a blocking dependent, is not: planned, and marked incomplete.
    rel = releases()
    del rel.packages["mid"]
    result = run_scan(context(store, rel), load_upload(store, lockfile(mid_lib="1.0.0")))
    [row] = result["remediation"]["results"]
    assert row["plan"]["status"] == "blocked" and row["incomplete"] == ["mid"] and not row["resolved"]
    assert row["actions"][0].startswith("Release metadata for mid is missing")


def test_scan_without_releases_skips_plans():
    store = base_store()
    result = run_scan(context(store), load_upload(store, lockfile()))
    assert result["remediation"] is None and result["total_results"] == 1


@pytest.mark.parametrize("lock", [
    {"lockfileVersion": 1, "dependencies": {}},
    {"lockfileVersion": 3, "packages": {"node_modules/x": {}}},  # no version
    ["not", "a", "lockfile"],
])
def test_malformed_uploads_raise_value_error(lock):
    with pytest.raises(ValueError):
        load_upload(base_store(), lock)


def test_workspaces_and_missing_dependencies_warn():
    lock = lockfile()
    lock["packages"]["packages/web"] = {"name": "web", "version": "0.1.0"}
    lock["packages"][""]["dependencies"]["ghost"] = "^1.0.0"
    warnings = load_upload(base_store(), lock).warnings
    assert any("workspace packages" in w and "packages/web" in w for w in warnings)
    assert any("ghost" in w for w in warnings)


# A live OSV record the graph lacks: GHSA-m (CVE-9, CRITICAL) affects mid < 1.0.5.
LIVE_RECORD = {
    "id": "GHSA-m", "aliases": ["CVE-9"], "summary": "mid is bad", "modified": "2026-01-01T00:00:00Z",
    "database_specific": {"severity": "CRITICAL"},
    "affected": [{"package": {"ecosystem": "npm", "name": "mid"},
                  "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.0.5"}]}]}],
}


class FakeOsv:
    def __init__(self, matches, records, error=None):
        self.matches, self.records, self.error, self.queried = matches, records, error, None

    def lookup(self, name_versions):
        self.queried = set(name_versions)
        if self.error:
            raise self.error
        return self.matches, self.records


def test_live_osv_adds_advisories_the_graph_lacks():
    osv = FakeOsv({("mid", "1.0.0"): {"GHSA-m"}}, {"GHSA-m": LIVE_RECORD})
    base = base_store()
    upload = load_upload(base, lockfile(), osv)

    # Only versions outside the corpus are queried; lib@1.0.0 is a corpus version.
    assert osv.queried == {("mid", "1.0.0"), ("tool", "2.0.0")}
    assert upload.unchecked == [] and not any("outside this dataset" in w for w in upload.warnings)
    assert upload.live_osv == {"queried": 2, "matched_versions": 1, "advisories_added": 1, "agree": 1,
                               "only_ours": 0, "only_osv": 0, "only_ours_examples": [], "only_osv_examples": []}
    assert upload.store.get_entity("GHSA-m")["properties"]["severity"] == "CRITICAL"
    assert [e["entity_id"] for e in upload.store.neighbors("GHSA-m", relation="FIXED_IN")] == ["npm:mid@1.0.5"]
    assert base.get_entity("GHSA-m") is None

    result = run_scan(context(base, releases()), upload)
    assert result["results"][0]["vulnerability_id"] == "GHSA-m" and result["results"][0]["fixed_in"] == ["npm:mid@1.0.5"]
    assert result["totals"]["by_severity"] == {"CRITICAL": 1, "HIGH": 1}


def test_live_osv_disagreement_is_reported():
    # OSV says tool@2.0.0 is hit by GHSA-m, but GHSA-m's ranges only cover mid.
    osv = FakeOsv({("mid", "1.0.0"): {"GHSA-m"}, ("tool", "2.0.0"): {"GHSA-m"}}, {"GHSA-m": LIVE_RECORD})
    upload = load_upload(base_store(), lockfile(), osv)
    assert upload.live_osv["only_osv"] == 1 and upload.live_osv["only_osv_examples"] == ["tool@2.0.0 GHSA-m"]
    assert any("disagree on 1" in w for w in upload.warnings)


def test_live_osv_failure_falls_back_to_the_graph():
    import requests
    osv = FakeOsv({}, {}, error=requests.ConnectionError("offline"))
    upload = load_upload(base_store(), lockfile(), osv)
    assert upload.live_osv is None and upload.unchecked == ["mid@1.0.0", "tool@2.0.0"]
    assert any("live OSV lookup failed" in w for w in upload.warnings)


def test_no_live_lookup_when_every_version_is_in_the_corpus():
    osv = FakeOsv({}, {})
    lock = {"lockfileVersion": 3, "packages": {"": {"name": "app", "dependencies": {"lib": "^1.0.0"}},
                                               "node_modules/lib": {"version": "1.0.0"}}}
    assert load_upload(base_store(), lock, osv).live_osv is None and osv.queried is None


class FakeRegistry:
    """Serves release entries from `packages`; anything else fails like a 404."""

    def __init__(self, packages):
        self.packages, self.calls = packages, []

    def fetch(self, names):
        self.calls.append(sorted(names))
        return ({n: self.packages[n] for n in names if n in self.packages},
                {n: "HTTPError: 404" for n in names if n not in self.packages})


def test_registry_fills_missing_release_metadata_round_by_round():
    full = releases()
    full.packages["mid"] = releases().packages["mid"] | {"versions": ["1.0.0", "1.1.0"], "manifests": {
        "1.0.0": {"dependencies": {"lib": "1.0.0"}, "deprecated": None},
        "1.1.0": {"dependencies": {"lib": "^1.0.2"}, "deprecated": None}}}
    # Round 1 has neither lib nor mid. Planning lib needs mid only once lib's own metadata is there.
    store = base_store()
    registry = FakeRegistry(full.packages)
    ctx = context(store, Releases({}))
    result = run_scan(ctx, load_upload(store, lockfile(mid_lib="1.0.0")), registry=registry)

    [row] = result["remediation"]["results"]
    assert registry.calls == [["lib"], ["mid"]]
    assert row["plan"]["status"] == "blocked" and row["resolved"] and row["incomplete"] == []
    assert any('mid 1.0.0 -> 1.1.0' in step for step in row["actions"])
    assert result["remediation"]["totals"]["releases_fetched"] == 2
    assert ctx.releases.packages == {}  # the shared context is not modified


def test_registry_failures_are_warned_and_not_retried():
    store = base_store()
    registry = FakeRegistry({})
    result = run_scan(context(store, Releases({})), load_upload(store, lockfile()), registry=registry)

    assert registry.calls == [["lib"]]
    assert result["remediation"]["results"][0]["plan"]["status"] == "no_metadata"
    assert any("registry fetch failed for 1 packages" in w and "lib: HTTPError: 404" in w
               for w in result["warnings"])
