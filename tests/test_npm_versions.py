import pytest

from entitygraph_rag.npm.versions import compare, fixed_versions, in_osv_range, is_affected, satisfies


@pytest.mark.parametrize(
    ("version", "version_range", "expected"),
    [
        ("1.13.1", "^1.10.0", True),
        ("2.0.0", "^1.10.0", False),
        ("0.2.5", "^0.2.0", True),
        ("0.3.0", "^0.2.0", False),       # caret on 0.x pins the minor
        ("0.0.4", "^0.0.3", False),       # ...and on 0.0.x pins the patch
        ("1.2.9", "~1.2.3", True),
        ("1.3.0", "~1.2.3", False),
        ("1.4.0", ">= 1.4.0 < 2", True),  # space after the operator, as in the wild
        ("1.5.0", "1.x", True),
        ("3.0.0", "^1.0.0 || ^3.0.0", True),
        ("1.5.0", "1.2.0 - 1.4.0", False),
        ("2.0.0-beta.1", "^1.0.0", False),
        ("1.3.0-beta.1", "^1.2.0", False),  # prereleases only match a range naming one on the same x.y.z
        ("1.2.0-beta.2", "^1.2.0-beta.1", True),
        ("4.0.0", "*", True),
    ],
)
def test_satisfies_npm_range_syntax(version, version_range, expected):
    assert satisfies(version, version_range) is expected


def test_compare_orders_prereleases_and_osv_zero():
    assert compare("1.14.7-beta.1", "1.14.7") == -1
    assert compare("1.10.0", "1.9.9") == 1
    assert compare("0", "0.0.1") == -1
    assert compare("0", "0") == 0


def semver_range(*events):
    return {"type": "SEMVER", "events": list(events)}


def test_in_osv_range_introduced_fixed():
    r = semver_range({"introduced": "0"}, {"fixed": "1.14.7"})
    assert in_osv_range("1.13.1", r)
    assert in_osv_range("1.14.7-beta.1", r)  # a prerelease of the fix is still before it
    assert not in_osv_range("1.14.7", r)


def test_in_osv_range_last_affected_and_multiple_windows():
    r = semver_range({"introduced": "2.0.0"}, {"last_affected": "2.3.0"})
    assert in_osv_range("2.3.0", r) and not in_osv_range("2.3.1", r) and not in_osv_range("1.9.0", r)

    # Two affected windows in one range, events deliberately out of order.
    r = semver_range({"introduced": "0.1.0"}, {"fixed": "0.1.10"}, {"fixed": "1.0.1"}, {"introduced": "1.0.0"})
    assert in_osv_range("0.1.7", r)
    assert not in_osv_range("0.5.0", r)
    assert in_osv_range("1.0.0", r)
    assert not in_osv_range("1.0.1", r)


def test_non_semver_ranges_never_match():
    assert not in_osv_range("1.0.0", {"type": "ECOSYSTEM", "events": [{"introduced": "0"}]})


def test_is_affected_uses_explicit_versions_list():
    entry = {"versions": ["1.2.9"], "ranges": [semver_range({"introduced": "0"}, {"fixed": "1.0.0"})]}
    assert is_affected("1.2.9", entry)
    assert is_affected("0.5.0", entry)
    assert not is_affected("1.3.0", entry)


def test_fixed_versions_are_sorted_semantically():
    entry = {"ranges": [semver_range({"introduced": "0"}, {"fixed": "1.10.0"}, {"introduced": "2.0.0"}, {"fixed": "2.1.0"}),
                        semver_range({"introduced": "0"}, {"fixed": "1.9.0"})]}
    assert fixed_versions(entry) == ["1.9.0", "1.10.0", "2.1.0"]
