"""npm version comparison, range checks, and OSV affected-range matching.

Built on `node-semver`, a Python port of npm's own `semver` package, so
`^`, `~`, `||`, x-ranges, hyphen ranges and prerelease rules behave the way
npm resolves them.

OSV's npm ranges are `SEMVER` ranges: a list of `introduced` / `fixed` /
`last_affected` events. They are evaluated per the OSV spec: walk the
events in version order, and a version is affected if the last event at or
below it is an `introduced`. `introduced: "0"` means "from the first
version".
"""

from functools import cmp_to_key, lru_cache

import nodesemver

ZERO = "0"


@lru_cache(maxsize=500_000)
def compare(a: str, b: str) -> int:
    """-1 / 0 / 1 semver order. OSV's "0" sorts below every version. Cached, like `satisfies`."""
    if a == ZERO or b == ZERO:
        return (a != ZERO) - (b != ZERO)
    return nodesemver.compare(_parse_version(a), _parse_version(b), False)


@lru_cache(maxsize=500_000)
def satisfies(version: str, version_range: str) -> bool:
    """Whether `version` is in an npm range, e.g. satisfies("1.13.1", "^1.10.0").

    Follows npm: a prerelease only satisfies a range that names a
    prerelease of the same major.minor.patch. Same result as
    `nodesemver.satisfies`, but remediation planning asks hundreds of
    thousands of (version, range) pairs, and node-semver re-parses both
    strings on every call, so parsed ranges, versions and results are cached.
    """
    parsed = _parse_range(version_range)
    return parsed is not None and parsed.test(_parse_version(version))


@lru_cache(maxsize=50_000)
def _parse_range(version_range: str) -> "nodesemver.Range | None":
    if not isinstance(version_range, str):
        raise nodesemver.InvalidTypeIncluded(f"must be str, but {version_range!r}")
    try:
        return nodesemver.make_range(version_range, False)
    except ValueError:  # an unparseable range matches nothing, as in nodesemver.satisfies
        return None


@lru_cache(maxsize=100_000)
def _parse_version(version: str) -> "nodesemver.SemVer":
    return nodesemver.make_semver(version, False)


def _sorted_events(events: list[dict]) -> list[tuple[str, str]]:
    flat = [(kind, v) for event in events for kind, v in event.items() if kind in ("introduced", "fixed", "last_affected")]
    return sorted(flat, key=cmp_to_key(lambda x, y: compare(x[1], y[1])))


def in_osv_range(version: str, osv_range: dict) -> bool:
    if osv_range.get("type") != "SEMVER":
        return False  # ECOSYSTEM / GIT ranges only occur on non-npm entries in this corpus
    affected = False
    for kind, bound in _sorted_events(osv_range["events"]):
        order = compare(version, bound)
        if kind == "introduced" and order >= 0:
            affected = True
        elif kind == "fixed" and order >= 0:
            affected = False
        elif kind == "last_affected" and order > 0:
            affected = False
    return affected


def is_affected(version: str, affected_entry: dict) -> bool:
    """Whether `version` is affected per one OSV `affected[]` entry (explicit list or ranges)."""
    if version in affected_entry.get("versions", []):
        return True
    return any(in_osv_range(version, r) for r in affected_entry.get("ranges", []))


def fixed_versions(affected_entry: dict) -> list[str]:
    """Every `fixed` event across an entry's SEMVER ranges, in version order."""
    fixed = {e["fixed"] for r in affected_entry.get("ranges", []) if r.get("type") == "SEMVER"
             for e in r["events"] if "fixed" in e}
    return sorted(fixed, key=cmp_to_key(compare))


def is_stable(version: str) -> bool:
    """A valid semver release without a prerelease tag. Old registry entries include non-semver strings."""
    parsed = nodesemver.parse(version, False)
    return parsed is not None and not parsed.prerelease


def sort_versions(versions) -> list[str]:
    return sorted(versions, key=cmp_to_key(compare))
