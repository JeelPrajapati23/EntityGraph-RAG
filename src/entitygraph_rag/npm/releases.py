"""Published versions and their declared dependencies, for remediation (Phase 9).

Two sources, merged per package:
- the trimmed packuments (scripts/fetch_npm_metadata.py): every published
  version string, but manifests only for versions in a corpus tree;
- release files (scripts/fetch_release_metadata.py, registry.trim_releases):
  manifests for every version, fetched only for packages remediation asks
  about.

A question the loaded data can't answer is recorded in `missing` (by
package name) and answered conservatively (unknown version list = no
candidates, unknown manifest = not accepted), so the fetch script can fill
the gaps and plan again.
"""

import json
from pathlib import Path

from .versions import is_stable, sort_versions


class Releases:
    def __init__(self, packages: dict[str, dict]):
        """packages: name -> {"versions": [every published version], "manifests": {version: {dependencies, deprecated}}}."""
        self.packages = packages
        self.missing: set[str] = set()
        self.touched: set[str] = set()
        self._sorted: dict[str, list[str]] = {}

    @classmethod
    def from_dirs(cls, packument_dir: Path, release_dir: Path | None = None) -> "Releases":
        packages = {}
        for path in sorted(packument_dir.glob("*.json")):
            p = json.loads(path.read_text(encoding="utf-8"))
            packages[p["name"]] = {"versions": p["all_versions"], "manifests": {
                v: {"dependencies": {d: s for key in ("dependencies", "optionalDependencies", "peerDependencies")
                                     for d, s in m.get(key, {}).items()},
                    "deprecated": m.get("deprecated")}
                for v, m in p["versions"].items() if not m.get("missing")}}
        for path in sorted(release_dir.glob("*.json")) if release_dir and release_dir.exists() else ():
            r = json.loads(path.read_text(encoding="utf-8"))
            entry = packages.setdefault(r["name"], {"versions": list(r["versions"]), "manifests": {}})
            entry["manifests"].update(r["versions"])
            entry["complete"] = True
        return cls(packages)

    @classmethod
    def from_file(cls, path: Path) -> "Releases":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path, names=None) -> None:
        """Write the packages in `names` (default: every package asked about) as one JSON file."""
        names = sorted(self.touched if names is None else names)
        path.write_text(json.dumps({n: self.packages[n] for n in names if n in self.packages}), encoding="utf-8")

    def stable_versions(self, name: str) -> list[str]:
        """Published non-prerelease versions, ascending. Empty (and recorded missing) if unknown."""
        self.touched.add(name)
        if name not in self.packages:
            self.missing.add(name)
            return []
        if name not in self._sorted:
            self._sorted[name] = sort_versions(v for v in self.packages[name]["versions"] if is_stable(v))
        return self._sorted[name]

    def manifest(self, name: str, version: str) -> dict | None:
        self.touched.add(name)
        found = self.packages.get(name, {}).get("manifests", {}).get(version)
        if found is None and not self.packages.get(name, {}).get("complete"):
            self.missing.add(name)
        return found

    def require_complete(self, name: str) -> None:
        """Record `name` as missing unless every version's manifest is loaded (e.g. to know which are deprecated)."""
        self.touched.add(name)
        if not self.packages.get(name, {}).get("complete"):
            self.missing.add(name)

    def deprecated(self, name: str, version: str) -> bool:
        """Only known for versions with a loaded manifest; unknown counts as not deprecated."""
        return bool((self.packages.get(name, {}).get("manifests", {}).get(version) or {}).get("deprecated"))
