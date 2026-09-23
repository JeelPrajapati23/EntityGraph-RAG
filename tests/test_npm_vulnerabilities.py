from entitygraph_rag.npm.vulnerabilities import build_vulnerability_edges, compare_with_osv, version_id

FOLLOW_REDIRECTS = {
    "id": "GHSA-74fj-2j2h-c42q",
    "affected": [
        {"package": {"ecosystem": "npm", "name": "follow-redirects"},
         "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.14.7"}]}]},
        {"package": {"ecosystem": "PyPI", "name": "follow-redirects"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]},
    ],
}
WITHDRAWN = {
    "id": "GHSA-xxxx-withdrawn",
    "withdrawn": "2024-01-01T00:00:00Z",
    "affected": [{"package": {"ecosystem": "npm", "name": "axios"},
                  "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}]}]}],
}
CORPUS = {
    ("follow-redirects", "1.13.1"): {"lock:axios", "lock:browser-sync"},
    ("follow-redirects", "1.15.0"): {"lock:jest"},
    ("follow-redirects", "1.14.7"): {"lock:karma"},
    ("axios", "0.21.1"): {"lock:axios"},
}


def by_relation(rows, relation):
    return [r for r in rows if r["relation"] == relation]


def test_affects_version_range_is_npm_only_and_verbatim():
    rows = build_vulnerability_edges([FOLLOW_REDIRECTS], CORPUS)
    [affects] = by_relation(rows, "AFFECTS_VERSION_RANGE")

    assert affects["object"] == "npm:follow-redirects"
    assert affects["ranges"] == FOLLOW_REDIRECTS["affected"][0]["ranges"]
    assert affects["source_url"] == "https://osv.dev/vulnerability/GHSA-74fj-2j2h-c42q"


def test_fixed_in_marks_whether_fix_is_in_a_tree():
    rows = build_vulnerability_edges([FOLLOW_REDIRECTS], CORPUS)
    [fixed] = by_relation(rows, "FIXED_IN")

    assert fixed["object"] == version_id("follow-redirects", "1.14.7")
    assert fixed["in_tree"] is True


def test_has_vulnerability_is_derived_from_ranges_with_lockfiles():
    rows = build_vulnerability_edges([FOLLOW_REDIRECTS], CORPUS)
    [edge] = by_relation(rows, "HAS_VULNERABILITY")

    assert edge["subject"] == "npm:follow-redirects@1.13.1"
    assert edge["extraction_method"] == "derived"
    assert edge["lockfile_doc_ids"] == ["lock:axios", "lock:browser-sync"]


def test_withdrawn_advisory_keeps_ranges_but_affects_nothing():
    rows = build_vulnerability_edges([WITHDRAWN], CORPUS)

    assert by_relation(rows, "AFFECTS_VERSION_RANGE")
    assert not by_relation(rows, "HAS_VULNERABILITY")


def test_compare_with_osv_reports_both_directions():
    rows = build_vulnerability_edges([FOLLOW_REDIRECTS], CORPUS)
    osv = [{"name": "follow-redirects", "version": "1.13.1", "vuln_ids": ["GHSA-74fj-2j2h-c42q", "GHSA-other"]}]

    check = compare_with_osv(rows, osv)

    assert check["agree"] == 1
    assert check["only_ours"] == []
    assert check["only_osv"] == [("follow-redirects", "1.13.1", "GHSA-other")]


def test_one_affects_edge_per_package_with_every_release_line():
    record = {"id": "GHSA-mm", "affected": [
        {"package": {"ecosystem": "npm", "name": "minimatch"},
         "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "3.1.4"}]}]},
        {"package": {"ecosystem": "npm", "name": "minimatch"},
         "ranges": [{"type": "SEMVER", "events": [{"introduced": "9.0.0"}, {"fixed": "9.0.7"}]}]},
    ]}
    rows = build_vulnerability_edges([record], {("minimatch", "3.0.4"): {"lock:a"}, ("minimatch", "9.0.1"): {"lock:b"}})

    [affects] = by_relation(rows, "AFFECTS_VERSION_RANGE")
    assert [r["events"][-1]["fixed"] for r in affects["ranges"]] == ["3.1.4", "9.0.7"]
    assert {r["object_version"] for r in by_relation(rows, "FIXED_IN")} == {"3.1.4", "9.0.7"}
    assert {r["subject_version"] for r in by_relation(rows, "HAS_VULNERABILITY")} == {"3.0.4", "9.0.1"}
