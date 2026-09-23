from reachfix.graph import NetworkXGraphStore
from reachfix.npm.graph_load import to_entity
from reachfix.npm.releases import Releases
from reachfix.npm.remediation import actions, is_resolved, plan_fix, summarize, vulnerable_copies
from reachfix.npm.versions import is_affected

# One lockfile, rooted at app@1.0.0:  app -> mid@1.0.0 -> lib@1.0.0, and app -> lib@1.0.0 directly.
# Advisories on lib:
#   GHSA-a  CVE-1  affects < 1.0.2          (on lib@1.0.0)
#   GHSA-b  CVE-1  affects 1.0.2 (< 1.0.3)  incomplete-fix follow-up sharing CVE-1
#   GHSA-c  CVE-2  affects 1.1.0 (< 1.1.1)  unrelated, only hits a newer release
LOCK = "lockfile:npm:app@1.0.0"
LIB_VERSIONS = ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.1.0", "1.1.1", "2.0.0-beta.1"]


def semver(introduced, fixed=None):
    events = [{"introduced": introduced}] + ([{"fixed": fixed}] if fixed else [])
    return {"type": "SEMVER", "events": events}


def build_store(app_lib="^1.0.0", mid_lib="^1.0.0", app_mid="^1.0.0", lib_ranges=None):
    lib_ranges = lib_ranges or {"GHSA-a": semver("0", "1.0.2"), "GHSA-b": semver("1.0.2", "1.0.3"),
                                "GHSA-c": semver("1.1.0", "1.1.1")}
    cve = {"GHSA-a": "CVE-1", "GHSA-b": "CVE-1", "GHSA-c": "CVE-2", "GHSA-d": "CVE-3"}
    nodes = [{"node_id": f"npm:{v}", "node_type": "PackageVersion", "name": v, "aliases": [v], "properties": {}}
             for v in ("app@1.0.0", "mid@1.0.0", "lib@1.0.0")]
    nodes += [{"node_id": "npm:lib", "node_type": "Package", "name": "lib", "aliases": ["lib"], "properties": {}}]
    nodes += [{"node_id": g, "node_type": "Vulnerability", "name": g, "aliases": [g, cve[g]],
               "properties": {"aliases": [cve[g]]}} for g in lib_ranges]

    def edge(s, rel, o, **props):
        return {"subject_id": s, "relation": rel, "object_id": o, "properties": props, "source_doc_id": "t"}

    def dep(frm, to, dep_name, version_range):
        return edge(f"npm:{frm}", "DEPENDS_ON", f"npm:{to}", dep_name=dep_name, version_range=version_range,
                    dependency_type="prod", lockfile_doc_ids=[LOCK])

    edges = [dep("app@1.0.0", "mid@1.0.0", "mid", app_mid), dep("mid@1.0.0", "lib@1.0.0", "lib", mid_lib),
             dep("app@1.0.0", "lib@1.0.0", "lib", app_lib)]
    edges += [edge(g, "AFFECTS_VERSION_RANGE", "npm:lib", ranges=[r], versions=[]) for g, r in lib_ranges.items()]
    edges += [edge("npm:lib@1.0.0", "HAS_VULNERABILITY", g, lockfile_doc_ids=[LOCK])
              for g, r in lib_ranges.items() if is_affected("1.0.0", {"ranges": [r]})]
    store = NetworkXGraphStore()
    store.load([to_entity(n) for n in nodes], edges)
    return store


def releases(lib_deprecated=(), mid=None, app=None):
    def package(manifests):
        return {"versions": list(manifests), "manifests": {v: {"dependencies": d, "deprecated": None}
                                                           for v, d in manifests.items()}, "complete": True}
    packages = {"lib": package({v: {} for v in LIB_VERSIONS}),
                "mid": package(mid or {"1.0.0": {"lib": "^1.0.0"}}),
                "app": package(app or {"1.0.0": {"mid": "^1.0.0", "lib": "^1.0.0"}})}
    for v in lib_deprecated:
        packages["lib"]["manifests"][v]["deprecated"] = "use a newer release"
    return Releases(packages)


def test_in_range_fix_clears_every_advisory_sharing_the_cve():
    plan = plan_fix(build_store(), releases(), LOCK, "npm:lib@1.0.0")

    # GHSA-b isn't on lib@1.0.0, but it shares CVE-1 with GHSA-a, so 1.0.2 (GHSA-a's own fix) isn't enough.
    assert plan["advisories"] == ["GHSA-a", "GHSA-b"]
    assert plan["lowest_safe_version"] == "1.0.3"
    assert plan["status"] == "in_range" and plan["target_version"] == "1.0.3"
    assert "npm update lib" in actions(plan)[0]


def test_prefers_versions_clear_of_other_advisories_and_not_deprecated():
    # Only 1.1.x fits; 1.1.0 is hit by GHSA-c, so 1.1.1 is picked.
    plan = plan_fix(build_store(app_lib="~1.1.0", mid_lib="~1.1.0"), releases(), LOCK, "npm:lib@1.0.0")
    assert plan["target_version"] == "1.1.1" and "still_affected_by" not in plan
    assert plan["lowest_safe_version"] == "1.0.3" and plan["lowest_safe_still_affected_by"] == []

    # A deprecated 1.0.3 loses to a clean, current 1.1.1; prereleases are never candidates.
    plan = plan_fix(build_store(), releases(lib_deprecated=["1.0.3"]), LOCK, "npm:lib@1.0.0")
    assert plan["target_version"] == "1.1.1" and plan["lowest_safe_version"] == "1.0.3"


def test_split_when_no_single_version_fits_every_range():
    plan = plan_fix(build_store(app_lib="~1.0.3", mid_lib="~1.1.1"), releases(), LOCK, "npm:lib@1.0.0")
    assert plan["status"] == "split"
    assert {d["dependent"]: d["admits"] for d in plan["dependents"]} == {"npm:app@1.0.0": "1.0.3", "npm:mid@1.0.0": "1.1.1"}


def test_blocked_dependent_is_upgraded_up_to_the_root():
    # mid@1.0.0 pins lib exactly; mid 1.2.0 is the first to allow a fix, and app@1.0.0 pins mid,
    # so the project itself has to move to app 2.0.0.
    store = build_store(mid_lib="1.0.0", app_mid="1.0.0")
    rel = releases(mid={"1.0.0": {"lib": "1.0.0"}, "1.1.0": {"lib": "1.0.0"}, "1.2.0": {"lib": "^1.0.3"}},
                   app={"1.0.0": {"mid": "1.0.0"}, "2.0.0": {"mid": "^1.2.0", "lib": "^1.0.0"}})
    plan = plan_fix(store, rel, LOCK, "npm:lib@1.0.0")

    assert plan["status"] == "blocked" and is_resolved(plan)
    mid = next(d for d in plan["dependents"] if d["dependent"] == "npm:mid@1.0.0")
    assert mid["upgrade"]["target_version"] == "1.2.0" and mid["upgrade"]["declares"] == {"lib": "^1.0.3"}
    assert mid["upgrade"]["status"] == "blocked"
    summary = summarize(plan)
    assert summary["root"]["app"]["version"] == "2.0.0" and summary["via"]["mid"]["version"] == "1.2.0"
    assert plan["override"] == {"package": "lib", "version": "1.0.3", "outside_ranges": ["npm:mid@1.0.0"]}
    text = "\n".join(actions(plan))
    assert "app 1.0.0 -> 2.0.0" in text and '"overrides": {"lib": "1.0.3"}' in text


def test_parent_upgrade_prefers_admitting_a_clean_fix():
    # The targets are GHSA-a and GHSA-b (same CVE), so lib 1.1.0 counts as fixed, but GHSA-c still hits it.
    # mid 1.1.0 allows only lib 1.1.0; mid 1.2.0 allows ^1.1.1, which is clean. mid 1.2.0 wins although it is higher.
    store = build_store(mid_lib="1.0.0", app_mid="^1.0.0")
    rel = releases(mid={"1.0.0": {"lib": "1.0.0"}, "1.1.0": {"lib": "1.1.0"}, "1.2.0": {"lib": "^1.1.1"}})
    plan = plan_fix(store, rel, LOCK, "npm:lib@1.0.0", {"GHSA-a"})

    mid = next(d for d in plan["dependents"] if d["dependent"] == "npm:mid@1.0.0")
    assert mid["upgrade"]["target_version"] == "1.2.0" and mid["upgrade"]["status"] == "in_range"


def test_blocker_with_no_upgrade_path_is_unresolved():
    store = build_store(mid_lib="1.0.0")
    plan = plan_fix(store, releases(mid={"1.0.0": {"lib": "1.0.0"}, "1.1.0": {"lib": "1.0.0"}}), LOCK, "npm:lib@1.0.0")
    assert plan["status"] == "blocked" and not is_resolved(plan)
    assert summarize(plan)["unresolved"]


def test_unfixed_advisory_is_removed_by_upgrading_dependents_that_drop_it():
    store = build_store(lib_ranges={"GHSA-d": semver("0")})  # every version affected
    rel = releases(mid={"1.0.0": {"lib": "^1.0.0"}, "1.3.0": {}},
                   app={"1.0.0": {"mid": "^1.0.0", "lib": "^1.0.0"}, "3.0.0": {"mid": "^1.3.0"}})
    plan = plan_fix(store, rel, LOCK, "npm:lib@1.0.0")

    assert plan["status"] == "no_fix" and plan["lowest_safe_version"] is None and is_resolved(plan)
    summary = summarize(plan)
    assert summary["refresh"]["mid"]["version"] == "1.3.0" and summary["refresh"]["mid"]["whys"] == {"drops lib"}
    assert summary["root"]["app"]["version"] == "3.0.0"


def test_vulnerable_root_is_upgraded_itself():
    store = build_store()
    store.upsert_edge({"subject_id": "npm:app@1.0.0", "relation": "HAS_VULNERABILITY", "object_id": "GHSA-a",
                       "properties": {"lockfile_doc_ids": [LOCK]}})
    store.upsert_edge({"subject_id": "GHSA-a", "relation": "AFFECTS_VERSION_RANGE", "object_id": "npm:app",
                       "properties": {"ranges": [semver("0", "1.5.0")], "versions": []}})
    rel = releases(app={"1.0.0": {}, "1.5.0": {}, "2.0.0": {}})
    plan = plan_fix(store, rel, LOCK, "npm:app@1.0.0")
    assert plan["status"] == "upgrade_root" and plan["target_version"] == "1.5.0"


def test_unknown_metadata_is_recorded_as_missing():
    rel = Releases({"lib": {"versions": LIB_VERSIONS, "manifests": {}}})
    plan_fix(build_store(mid_lib="1.0.0"), rel, LOCK, "npm:lib@1.0.0")
    # lib: deprecation unknown; mid: newer manifests unknown; app: whether a newer app drops mid
    assert rel.missing == {"lib", "mid", "app"}


def test_vulnerable_copies_are_per_lockfile():
    rows = [{"relation": "HAS_VULNERABILITY", "subject": "npm:lib@1.0.0", "lockfile_doc_ids": ["l1", "l2"]},
            {"relation": "HAS_VULNERABILITY", "subject": "npm:lib@1.0.0", "lockfile_doc_ids": ["l1"]},
            {"relation": "FIXED_IN", "subject": "GHSA-a", "object": "npm:lib@1.0.2"}]
    assert vulnerable_copies(rows) == [("l1", "npm:lib@1.0.0"), ("l2", "npm:lib@1.0.0")]
