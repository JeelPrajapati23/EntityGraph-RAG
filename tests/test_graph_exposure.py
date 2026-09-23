import pytest

from reachfix.graph import NetworkXGraphStore
from reachfix.graph.exposure import dependency_paths, exposed_lockfiles, exposure
from reachfix.npm.graph_load import dependency_to_edge, record_to_edge, root_of_lockfile, to_entity

# Two lockfiles share app@1.0.0 but resolved its `lib` dep differently:
# lock:a has lib@1.0.0 (vulnerable), lock:b has lib@1.1.0 (fixed).
#   lock:a: app@1 -> lib@1.0.0 -> deep@1 (vulnerable, 2 hops)
#   lock:b: app@1 -> lib@1.1.0 ; app@1 -> peer@1 (peer dep)
VERSIONS = ["app@1.0.0", "lib@1.0.0", "lib@1.1.0", "deep@1.0.0", "peer@1.0.0"]


def dep(frm, to, lockfiles, dependency_type="prod", registry_check="match"):
    (fn, fv), (tn, tv) = frm.split("@"), to.split("@")
    return {"from_name": fn, "from_version": fv, "to_name": tn, "to_version": tv, "dep_name": tn,
            "version_range": "^1.0.0", "declared_spec": "^1.0.0", "dependency_type": dependency_type,
            "range_satisfied": True, "registry_check": registry_check, "registry_spec": "^1.0.0",
            "lockfile_doc_ids": lockfiles, "occurrences": []}


def has_vuln(version, osv_id, lockfiles):
    return {"relation": "HAS_VULNERABILITY", "extraction_method": "derived", "subject": f"npm:{version}",
            "object": osv_id, "lockfile_doc_ids": lockfiles, "source_doc_id": osv_id,
            "source_url": f"https://osv.dev/vulnerability/{osv_id}"}


@pytest.fixture
def store():
    nodes = [{"node_id": f"npm:{v}", "node_type": "PackageVersion", "name": v, "aliases": [v], "properties": {}}
             for v in VERSIONS]
    nodes += [{"node_id": g, "node_type": "Vulnerability", "name": g, "aliases": [g], "properties": {}}
              for g in ("GHSA-lib", "GHSA-deep")]
    deps = [dep("app@1.0.0", "lib@1.0.0", ["lock:a"]), dep("app@1.0.0", "lib@1.1.0", ["lock:b"]),
            dep("lib@1.0.0", "deep@1.0.0", ["lock:a"], registry_check="range_differs"),
            dep("app@1.0.0", "peer@1.0.0", ["lock:b"], dependency_type="peer")]
    vulns = [has_vuln("lib@1.0.0", "GHSA-lib", ["lock:a"]), has_vuln("deep@1.0.0", "GHSA-deep", ["lock:a"])]
    s = NetworkXGraphStore()
    s.load([to_entity(n) for n in nodes], [dependency_to_edge(d) for d in deps] + [record_to_edge(v) for v in vulns])
    return s


def test_walk_is_scoped_to_one_lockfile(store):
    assert set(dependency_paths(store, "npm:app@1.0.0", "lock:a")) == {"npm:app@1.0.0", "npm:lib@1.0.0", "npm:deep@1.0.0"}
    assert set(dependency_paths(store, "npm:app@1.0.0", "lock:b")) == {"npm:app@1.0.0", "npm:lib@1.1.0", "npm:peer@1.0.0"}


def test_walk_options(store):
    assert set(dependency_paths(store, "npm:app@1.0.0", "lock:b", dependency_types={"prod"})) == {
        "npm:app@1.0.0", "npm:lib@1.1.0"}
    assert set(dependency_paths(store, "npm:app@1.0.0", "lock:a", max_depth=1)) == {"npm:app@1.0.0", "npm:lib@1.0.0"}


def test_exposure_returns_paths_sorted_by_depth(store):
    hits = exposure(store, "npm:app@1.0.0", "lock:a")

    assert [(h["vulnerability_id"], h["depth"]) for h in hits] == [("GHSA-lib", 1), ("GHSA-deep", 2)]
    assert hits[1]["path"] == ["npm:app@1.0.0", "npm:lib@1.0.0", "npm:deep@1.0.0"]
    assert exposure(store, "npm:app@1.0.0", "lock:b") == []  # same root, fixed tree
    assert [h["vulnerability_id"] for h in exposure(store, "npm:app@1.0.0", "lock:a", vulnerability_ids={"GHSA-deep"})] == ["GHSA-deep"]


def test_exposed_lockfiles(store):
    assert exposed_lockfiles(store, "GHSA-deep") == {"lock:a": ["npm:deep@1.0.0"]}


def test_depends_on_provenance_lists_lockfiles_plus_registry_when_it_agrees(store):
    [edge] = store.neighbors("npm:app@1.0.0", relation="DEPENDS_ON")[:1]
    assert [p["source_doc_id"] for p in edge["provenance"]] == ["lock:a", "npm-registry:app"]
    assert edge["properties"]["version_range"] == "^1.0.0" and "from_name" not in edge["properties"]

    [deep] = store.neighbors("npm:lib@1.0.0", relation="DEPENDS_ON")
    assert [p["source_doc_id"] for p in deep["provenance"]] == ["lock:a"]  # registry disagreed


def test_merged_condition_edges_keep_one_provenance_entry_per_chunk():
    row = {"relation": "EXPLOITABLE_WHEN", "extraction_method": "llm", "subject": "GHSA-a", "object": "GHSA-a::cond::0",
           "confidence": 0.95, "source_doc_id": "GHSA-a", "source_url": "u", "source_chunk_id": "GHSA-a::0",
           "extracted_at": "t", "sources": [
               {"condition_id": "c0", "source_chunk_id": "GHSA-a::0", "evidence": "e0", "evidence_match": "exact", "confidence": 0.95},
               {"condition_id": "c1", "source_chunk_id": "GHSA-a::2", "evidence": "e1", "evidence_match": "fuzzy", "confidence": 0.9}]}
    edge = record_to_edge(row)
    assert [p["source_chunk_id"] for p in edge["provenance"]] == ["GHSA-a::0", "GHSA-a::2"]
    assert edge["properties"] == {} and edge["confidence"] == 0.95


def test_root_of_lockfile():
    assert root_of_lockfile("lockfile:npm:@vue/cli-service@4.5.13") == "npm:@vue/cli-service@4.5.13"
    with pytest.raises(ValueError):
        root_of_lockfile("npm-registry:axios")
