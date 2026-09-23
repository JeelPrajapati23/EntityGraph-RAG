"""Read installed packages out of an npm package-lock.json (lockfileVersion 2 or 3).

The `packages` map is keyed by install path ("node_modules/a/node_modules/b"),
not by dependency depth. npm hoists packages, so the nesting stays shallow
however deep the logical tree goes. This module only lists what is
installed. `dependencies.py` rebuilds the DEPENDS_ON edges.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

NODE_MODULES = "node_modules/"


@dataclass(frozen=True)
class InstalledPackage:
    path: str      # key in the lockfile's `packages` map
    name: str      # real package name (differs from the path for npm aliases)
    version: str
    resolved: str | None
    optional: bool
    dependencies: dict[str, str] = field(default_factory=dict)
    optional_dependencies: dict[str, str] = field(default_factory=dict)
    peer_dependencies: dict[str, str] = field(default_factory=dict)
    peer_dependencies_meta: dict[str, dict] = field(default_factory=dict)


def load_lockfile(path: Path) -> dict:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("lockfileVersion", 1) < 2 or "packages" not in lock:
        raise ValueError(f"{path}: lockfileVersion {lock.get('lockfileVersion')} has no `packages` map; need v2 or v3")
    return lock


def name_from_path(path: str) -> str:
    """"node_modules/a/node_modules/@s/b" -> "@s/b"."""
    idx = path.rfind(NODE_MODULES)
    if idx == -1:
        raise ValueError(f"not a node_modules install path: {path!r}")
    return path[idx + len(NODE_MODULES):]


def installed_packages(lock: dict) -> list[InstalledPackage]:
    """Every installed registry package.

    Skips the lockfile's own root entry (""), workspace links, and workspace
    source dirs (paths outside node_modules), none of which are registry
    packages.
    """
    packages = []
    for path, entry in lock["packages"].items():
        if NODE_MODULES not in path or entry.get("link"):
            continue
        packages.append(
            InstalledPackage(
                path=path,
                # An aliased install ("foo": "npm:bar@1") sits at node_modules/foo but records name "bar".
                name=entry.get("name") or name_from_path(path),
                version=entry["version"],
                resolved=entry.get("resolved"),
                optional=bool(entry.get("optional")),
                dependencies=entry.get("dependencies", {}),
                optional_dependencies=entry.get("optionalDependencies", {}),
                peer_dependencies=entry.get("peerDependencies", {}),
                peer_dependencies_meta=entry.get("peerDependenciesMeta", {}),
            )
        )
    return packages


def unique_name_versions(packages: list[InstalledPackage]) -> set[tuple[str, str]]:
    return {(p.name, p.version) for p in packages}
