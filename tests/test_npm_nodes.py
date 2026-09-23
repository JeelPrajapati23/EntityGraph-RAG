import pytest

from reachfix.npm.licenses import parse_license
from reachfix.npm.lookup import NodeLookup
from reachfix.npm.nodes import build_nodes, dangling_endpoints, dependency_edge_endpoints
from reachfix.npm.projects import Project


@pytest.mark.parametrize(
    ("raw", "ids", "operator", "expression"),
    [
        ("MIT", ("MIT",), None, "MIT"),
        ("(MIT OR CC0-1.0)", ("MIT", "CC0-1.0"), "OR", "MIT OR CC0-1.0"),
        ("(MIT AND Zlib)", ("MIT", "Zlib"), "AND", "MIT AND Zlib"),
        ("Apache 2.0", ("Apache-2.0",), None, "Apache-2.0"),
        ("AFLv2.1 OR BSD", ("AFL-2.1", "BSD"), "OR", "AFL-2.1 OR BSD"),  # "BSD" is kept, not guessed
        ("(MIT OR (Apache-2.0 AND BSD-3-Clause))", ("(MIT OR (Apache-2.0 AND BSD-3-Clause))",), None,
         "(MIT OR (Apache-2.0 AND BSD-3-Clause))"),  # nested: kept whole
    ],
)
def test_parse_license(raw, ids, operator, expression):
    parsed = parse_license(raw)
    assert (parsed.ids, parsed.operator, parsed.expression) == (ids, operator, expression)


def test_parse_license_empty():
    assert parse_license(None) is None and parse_license("  ") is None


PACKUMENTS = {
    "axios": {"maintainers": ["jasonsaayman", "mzabriskie"], "time": {"0.21.1": "2020-12-22T00:00:00Z"},
              "all_versions": ["0.21.1", "0.21.2"],
              "versions": {"0.21.1": {"license": "MIT", "deprecated": None}}},
    "follow-redirects": {"maintainers": ["rubenverborgh"], "time": {"1.13.1": "2020-12-10T00:00:00Z"},
                         "all_versions": ["1.13.1", "1.14.7"],
                         "versions": {"1.13.1": {"license": "(MIT OR CC0-1.0)", "deprecated": "use 1.14"}}},
}
ADVISORIES = [
    {"id": "GHSA-74fj-2j2h-c42q", "aliases": ["CVE-2022-0155"], "summary": "leak",
     "database_specific": {"severity": "HIGH"},
     "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N"}, {"type": "CVSS_V4", "score": "CVSS:4.0/AV:N"}],
     "affected": [{"package": {"ecosystem": "npm", "name": "follow-redirects"}},
                  {"package": {"ecosystem": "npm", "name": "follow-redirects-extra"}}]},
    {"id": "GHSA-aaaa-bbbb-cccc", "aliases": ["CVE-2022-0155", "GHSA-74fj-2j2h-c42q"], "affected": []},
]
CORPUS = {("axios", "0.21.1"): {"lock:axios"}, ("follow-redirects", "1.13.1"): {"lock:axios"}}


@pytest.fixture(scope="module")
def built():
    nodes, edges = build_nodes(CORPUS, PACKUMENTS.get, ADVISORIES, [Project("axios", "0.21.1", "2020-12-23")],
                               [("follow-redirects", "1.14.7")])
    return {n["node_id"]: n for n in nodes}, edges


def test_version_nodes_carry_tree_root_and_registry_facts(built):
    nodes, _ = built
    root = nodes["npm:axios@0.21.1"]["properties"]
    assert root["is_root"] and root["in_tree"] and root["published_at"] == "2020-12-22T00:00:00Z"

    fixed = nodes["npm:follow-redirects@1.14.7"]["properties"]
    assert not fixed["in_tree"] and fixed["published"] is True and fixed["lockfile_doc_ids"] == []
    assert nodes["npm:follow-redirects@1.13.1"]["properties"]["deprecated"] == "use 1.14"


def test_packages_include_advisory_only_names(built):
    nodes, _ = built
    assert nodes["npm:follow-redirects-extra"]["node_type"] == "Package"


def test_vulnerability_nodes_stay_separate_and_prefer_cvss_v4(built):
    nodes, _ = built
    vuln = nodes["GHSA-74fj-2j2h-c42q"]["properties"]
    assert vuln["cvss_vector"] == "CVSS:4.0/AV:N" and vuln["severity"] == "HIGH"
    assert "GHSA-aaaa-bbbb-cccc" in nodes


def test_registry_edges(built):
    nodes, edges = built
    rel = {(e["relation"], e["subject"], e["object"]): e for e in edges}

    assert ("VERSION_OF", "npm:follow-redirects@1.14.7", "npm:follow-redirects") in rel
    assert ("MAINTAINED_BY", "npm:axios", "npm-user:mzabriskie") in rel
    lic = rel[("LICENSED_UNDER", "npm:follow-redirects@1.13.1", "license:CC0-1.0")]
    assert (lic["expression"], lic["operator"]) == ("MIT OR CC0-1.0", "OR")
    assert lic["source_url"] == "https://registry.npmjs.org/follow-redirects"
    assert dangling_endpoints(list(nodes.values()), edges) == []


def test_dangling_endpoints_are_reported(built):
    nodes, _ = built
    dep = dependency_edge_endpoints({"from_name": "axios", "from_version": "0.21.1",
                                     "to_name": "follow-redirects", "to_version": "9.9.9"})
    assert dangling_endpoints(list(nodes.values()), [dep]) == [("DEPENDS_ON", "npm:follow-redirects@9.9.9")]


@pytest.fixture(scope="module")
def lookup(built):
    return NodeLookup(list(built[0].values()))


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("CVE-2022-0155", ["GHSA-74fj-2j2h-c42q", "GHSA-aaaa-bbbb-cccc"]),  # a CVE shared by two advisories
        ("cve-2022-0155", ["GHSA-74fj-2j2h-c42q", "GHSA-aaaa-bbbb-cccc"]),
        ("ghsa-74fj-2j2h-c42q", ["GHSA-74fj-2j2h-c42q"]),  # an advisory id resolves to itself only
        ("CVE-1999-0001", []),
        ("axios@0.21.1", ["npm:axios@0.21.1"]),
        ("Follow-Redirects", ["npm:follow-redirects"]),
        ("follow redirects", ["npm:follow-redirects"]),
        ("axioss", ["npm:axios"]),
        ("totally-unrelated", []),
    ],
)
def test_lookup(lookup, query, expected):
    assert lookup.resolve(query) == expected
