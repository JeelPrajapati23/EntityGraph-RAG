"""Resolve a name typed in a query to node ids in the DepGraph node table.

In order:
1. An advisory id (GHSA-/MAL-) that is a node: that node alone.
2. Any other advisory-style id (CVE-, or a GHSA id only seen as an alias):
   every Vulnerability that lists it as an alias. One CVE can belong to
   several advisories (an advisory and its incomplete-fix follow-up), so
   this returns a list.
3. "name@version": that PackageVersion.
4. A package name, case-insensitive.
5. A fuzzy match on package names, with "-", "_", "." and "/" treated alike
   ("follow redirects" -> follow-redirects). Only one best match, at
   FUZZY_THRESHOLD or above.

The finance-era `resolution.normalize_name` is not reused: it drops words
like "co" and "group", which are real npm package names.
"""

import re
from collections import defaultdict

from rapidfuzz import fuzz, process

FUZZY_THRESHOLD = 90
_ADVISORY_ID_RE = re.compile(r"^(CVE|GHSA|MAL)-", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"[-_./\s]+")


def fuzzy_key(name: str) -> str:
    return _SEPARATOR_RE.sub(" ", name.lower().lstrip("@")).strip()


class NodeLookup:
    def __init__(self, nodes: list[dict]):
        self.nodes = {n["node_id"]: n for n in nodes}
        self._vuln_ids: dict[str, str] = {}  # upper-cased id -> id (GHSA ids are mixed case)
        self._vulns_by_alias: dict[str, list[str]] = defaultdict(list)
        self._packages: dict[str, str] = {}
        self._versions: dict[str, str] = {}
        for n in nodes:
            if n["node_type"] == "Vulnerability":
                self._vuln_ids[n["node_id"].upper()] = n["node_id"]
                for alias in n["aliases"]:
                    self._vulns_by_alias[alias.upper()].append(n["node_id"])
            elif n["node_type"] == "Package":
                self._packages[n["name"].lower()] = n["node_id"]
            elif n["node_type"] == "PackageVersion":
                self._versions[n["name"].lower()] = n["node_id"]
        self._fuzzy_packages = {fuzzy_key(name): node_id for name, node_id in self._packages.items()}

    def resolve(self, query: str) -> list[str]:
        text = query.strip()
        if _ADVISORY_ID_RE.match(text):
            upper = text.upper()
            if upper in self._vuln_ids:
                return [self._vuln_ids[upper]]
            return sorted(self._vulns_by_alias.get(upper, []))

        lower = text.lower()
        if lower in self._versions:
            return [self._versions[lower]]
        if lower in self._packages:
            return [self._packages[lower]]

        if not self._fuzzy_packages:
            return []
        best = process.extractOne(fuzzy_key(text), self._fuzzy_packages.keys(), scorer=fuzz.ratio)
        if best is not None and best[1] >= FUZZY_THRESHOLD:
            return [self._fuzzy_packages[best[0]]]
        return []
