from reachfix.npm.osv import normalize_modified
from reachfix.npm.projects import Project
from reachfix.npm.registry import maintainer_usernames, normalize_license, packument_url, trim_packument

PACKUMENT = {
    "name": "follow-redirects",
    "dist-tags": {"latest": "1.15.9"},
    "maintainers": [{"name": "rubenverborgh", "email": "x@example.com"}, "olalonde <y@example.com>"],
    "time": {"created": "2014-01-01T00:00:00.000Z", "1.13.1": "2020-12-10T00:00:00.000Z"},
    "versions": {
        "1.13.1": {"license": "MIT", "dependencies": {"debug": "^3.0.0"}, "readme": "x" * 1000},
        "1.14.7": {"license": {"type": "MIT", "url": "https://example.com"}},
    },
}


def test_packument_url_escapes_scope_slash_only():
    assert packument_url("axios") == "https://registry.npmjs.org/axios"
    assert packument_url("@babel/core") == "https://registry.npmjs.org/@babel%2Fcore"


def test_maintainer_usernames_drop_emails():
    assert maintainer_usernames(PACKUMENT["maintainers"]) == ["olalonde", "rubenverborgh"]
    assert maintainer_usernames(None) == []


def test_normalize_license_shapes():
    assert normalize_license({"license": "MIT"}) == "MIT"
    assert normalize_license({"license": {"type": "ISC"}}) == "ISC"
    assert normalize_license({"licenses": [{"type": "MIT"}, {"type": "Apache-2.0"}]}) == "MIT OR Apache-2.0"
    assert normalize_license({"license": "  "}) is None
    assert normalize_license({}) is None


def test_trim_packument_keeps_only_wanted_versions():
    trimmed = trim_packument(PACKUMENT, {"1.13.1", "0.0.1"})

    assert set(trimmed["versions"]) == {"1.13.1", "0.0.1"}
    assert trimmed["versions"]["1.13.1"]["license"] == "MIT"
    assert trimmed["versions"]["1.13.1"]["dependencies"] == {"debug": "^3.0.0"}
    assert "readme" not in trimmed["versions"]["1.13.1"]
    assert trimmed["versions"]["0.0.1"] == {"missing": True}
    assert trimmed["all_versions"] == ["1.13.1", "1.14.7"]
    assert trimmed["time"]["1.13.1"].startswith("2020-12-10")
    assert "x@example.com" not in str(trimmed)


def test_project_spec_and_slug():
    p = Project(name="@vue/cli-service", version="4.5.13", resolve_before="2021-05-09")

    assert p.spec == "@vue/cli-service@4.5.13"
    assert p.slug == "vue__cli-service@4.5.13"


def test_osv_modified_compares_across_precisions():
    assert normalize_modified("2026-09-10T03:49:10.642592Z") == normalize_modified("2026-09-10T03:49:10.642592133Z")
    assert normalize_modified("2026-09-10T03:49:10.6Z") == "2026-09-10T03:49:10.600000Z"
    assert normalize_modified("2026-09-10T03:49:10Z") == "2026-09-10T03:49:10Z"
    assert normalize_modified("2026-09-10T03:49:10.642592Z") != normalize_modified("2026-09-10T03:49:10.642593Z")
