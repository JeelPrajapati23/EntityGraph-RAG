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
    assert (base.node_count(), base.edge_count()) == (3, 2)


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
    assert "lib" in row["incomplete"] and not row["resolved"]
    assert any("release metadata missing" in w for w in result["warnings"])


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
