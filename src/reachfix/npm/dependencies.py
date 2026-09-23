"""Rebuild logical DEPENDS_ON edges from a lockfile's hoisted install layout.

npm hoists packages, so an entry's place in `node_modules/` says nothing
about who depends on it. For each dependency an installed package
declares, this finds the copy Node would load: look in the package's own
`node_modules` first, then in each enclosing `node_modules` up to the top.

Each edge keeps the declared range and dependency type, records whether
the resolved version satisfies that range, and is checked against the
registry's copy of that version's declared dependencies.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .lockfile import NODE_MODULES, InstalledPackage, installed_packages
from .registry import declared_dependencies
from .versions import satisfies

DEPENDENCY_TYPES = ("prod", "optional", "peer")
ALIAS_PREFIX = "npm:"


def parent_dir(path: str) -> str:
    """The package dir whose node_modules holds `path`: "node_modules/a/node_modules/@s/b" -> "node_modules/a"."""
    return path[: path.rfind(NODE_MODULES)].rstrip("/")


def resolve_install_path(from_path: str, dep_name: str, packages: dict) -> str | None:
    """Where Node would load `dep_name` from when required inside `from_path`."""
    base = from_path
    while True:
        candidate = f"{base}/{NODE_MODULES}{dep_name}" if base else f"{NODE_MODULES}{dep_name}"
        if candidate in packages:
            return candidate
        if not base:
            return None
        base = parent_dir(base)


def split_alias(spec: str) -> str:
    """The version range of a declared spec: "npm:string-width@^4.2.0" -> "^4.2.0"."""
    if spec.startswith(ALIAS_PREFIX):
        target = spec[len(ALIAS_PREFIX):]
        at = target.rfind("@")
        return target[at + 1:] if at > 0 else "*"
    return spec


@dataclass(frozen=True)
class Dependency:
    source: InstalledPackage
    dep_name: str          # the key as declared; differs from target.name for an npm alias
    spec: str              # declared spec, verbatim
    dependency_type: str   # prod / optional / peer
    target: InstalledPackage | None  # None if nothing in the tree satisfies the require

    @property
    def peer_optional(self) -> bool:
        return bool(self.source.peer_dependencies_meta.get(self.dep_name, {}).get("optional"))


def declared(pkg: InstalledPackage) -> Iterable[tuple[str, str, str]]:
    for dep_type, deps in zip(DEPENDENCY_TYPES, (pkg.dependencies, pkg.optional_dependencies, pkg.peer_dependencies)):
        for dep_name, spec in deps.items():
            yield dep_type, dep_name, spec


def resolve_dependencies(lock: dict) -> list[Dependency]:
    """Every dependency declared by every installed package, resolved to the copy Node would load.

    The lockfile root ("") is the scratch project that installed the corpus
    root, so its own dependencies are not package edges. A dependency that
    resolves to a workspace link rather than a registry package is left
    unresolved.
    """
    packages = lock["packages"]
    by_path = {p.path: p for p in installed_packages(lock)}
    resolved = []
    for pkg in by_path.values():
        for dep_type, dep_name, spec in declared(pkg):
            target_path = resolve_install_path(pkg.path, dep_name, packages)
            resolved.append(Dependency(pkg, dep_name, spec, dep_type, by_path.get(target_path)))
    return resolved


def registry_check(dep: Dependency, registry_deps: dict[str, dict[str, str]] | None) -> tuple[str, str | None]:
    """Compare a lockfile dependency with the registry's declaration for the same version.

    Returns (status, registry spec). Status is one of: match, range_differs,
    type_differs, not_declared, no_registry_data.
    """
    if registry_deps is None:
        return "no_registry_data", None
    spec = registry_deps[dep.dependency_type].get(dep.dep_name)
    if spec is not None:
        return ("match" if spec == dep.spec else "range_differs"), spec
    for other in DEPENDENCY_TYPES:
        if dep.dep_name in registry_deps[other]:
            return "type_differs", registry_deps[other][dep.dep_name]
    return "not_declared", None


RegistryLookup = Callable[[str, str], dict | None]  # (name, version) -> trimmed version metadata


def registry_deps_for(lookup: RegistryLookup, name: str, version: str) -> dict[str, dict[str, str]] | None:
    meta = lookup(name, version)
    if meta is None or meta.get("missing"):
        return None
    return declared_dependencies(meta)


def build_edges(lockfile_deps: dict[str, list[Dependency]], lookup: RegistryLookup) -> tuple[list[dict], list[dict]]:
    """Merge resolved dependencies from every lockfile into version-level edges.

    `lockfile_deps` maps a lockfile doc_id to its resolved dependencies. The
    same (source version, dep, type, target version) fact found in several
    lockfiles, or at several paths in one, becomes one edge listing every
    occurrence. Occurrences are kept per lockfile because the same source
    version can resolve a dep to different target versions in different
    trees, so a traversal from one root should only follow its own
    lockfile's edges.

    Returns (edges, unresolved).
    """
    edges: dict[tuple, dict] = {}
    unresolved = []
    for doc_id, deps in lockfile_deps.items():
        for dep in deps:
            src = dep.source
            if dep.target is None:
                unresolved.append(
                    {
                        "lockfile_doc_id": doc_id,
                        "from_name": src.name,
                        "from_version": src.version,
                        "from_path": src.path,
                        "dep_name": dep.dep_name,
                        "version_range": split_alias(dep.spec),
                        "dependency_type": dep.dependency_type,
                        "peer_optional": dep.peer_optional,
                    }
                )
                continue
            key = (src.name, src.version, dep.dep_name, dep.dependency_type, dep.target.name, dep.target.version)
            edge = edges.get(key)
            if edge is None:
                status, registry_spec = registry_check(dep, registry_deps_for(lookup, src.name, src.version))
                edge = edges[key] = {
                    "from_name": src.name,
                    "from_version": src.version,
                    "to_name": dep.target.name,
                    "to_version": dep.target.version,
                    "dep_name": dep.dep_name,
                    "version_range": split_alias(dep.spec),
                    "declared_spec": dep.spec,
                    "dependency_type": dep.dependency_type,
                    # False happens for peers: --legacy-peer-deps installs whatever is already there.
                    # Also False for a non-semver spec (a dist-tag or URL); none occur in this corpus.
                    "range_satisfied": satisfies(dep.target.version, split_alias(dep.spec)),
                    "registry_check": status,
                    "registry_spec": registry_spec,
                    "lockfile_doc_ids": [],
                    "occurrences": [],
                }
            if doc_id not in edge["lockfile_doc_ids"]:
                edge["lockfile_doc_ids"].append(doc_id)
            edge["occurrences"].append({"lockfile_doc_id": doc_id, "from_path": src.path, "to_path": dep.target.path})
    return list(edges.values()), unresolved


def registry_only_declarations(packages: Iterable[InstalledPackage], lookup: RegistryLookup) -> list[dict]:
    """Deps the registry declares for a version that its lockfile entry does not."""
    missing = []
    for pkg in packages:
        registry_deps = registry_deps_for(lookup, pkg.name, pkg.version)
        if registry_deps is None:
            continue
        lock_names = {dep_name for _, dep_name, _ in declared(pkg)}
        for dep_type, deps in registry_deps.items():
            for dep_name, spec in deps.items():
                if dep_name not in lock_names:
                    missing.append({"name": pkg.name, "version": pkg.version, "dep_name": dep_name,
                                    "dependency_type": dep_type, "registry_spec": spec})
    return missing
