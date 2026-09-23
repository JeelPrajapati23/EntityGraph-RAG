"""Dependency-tree and vulnerability-exposure queries for the DepGraph schema.

Written only against GraphStore, like queries.py. DEPENDS_ON edges are
version-level and shared across lockfiles, so each traversal is scoped to
one lockfile: an edge is followed only if its `lockfile_doc_ids` property
includes that lockfile. Without the filter, a walk from one root could
cross into a sub-tree another project resolved differently.

Paths are shortest (fewest hops) by breadth-first search.
"""

from collections import deque

from .store import GraphStore

DEPENDS_ON = "DEPENDS_ON"
HAS_VULNERABILITY = "HAS_VULNERABILITY"


def _in_lockfile(edge: dict, lockfile_doc_id: str | None) -> bool:
    return lockfile_doc_id is None or lockfile_doc_id in edge.get("properties", {}).get("lockfile_doc_ids", ())


def dependency_paths(
    store: GraphStore,
    root_id: str,
    lockfile_doc_id: str | None,
    *,
    max_depth: int | None = None,
    dependency_types: set[str] | None = None,
) -> dict[str, list[str]]:
    """version id -> shortest DEPENDS_ON path from root_id (both ends included) for every reachable version.

    dependency_types, if given, limits the walk to those edge types
    (prod / optional / peer). By default all are followed, since a peer is
    loaded from the dependent's own location like any other dependency.
    """
    paths = {root_id: [root_id]}
    queue = deque([root_id])
    while queue:
        current = queue.popleft()
        if max_depth is not None and len(paths[current]) - 1 >= max_depth:
            continue
        for edge in store.neighbors(current, relation=DEPENDS_ON, direction="out"):
            target = edge["entity_id"]
            if target in paths or not _in_lockfile(edge, lockfile_doc_id):
                continue
            if dependency_types is not None and edge["properties"].get("dependency_type") not in dependency_types:
                continue
            paths[target] = paths[current] + [target]
            queue.append(target)
    return paths


def exposure(
    store: GraphStore,
    root_id: str,
    lockfile_doc_id: str | None,
    *,
    max_depth: int | None = None,
    vulnerability_ids: set[str] | None = None,
) -> list[dict]:
    """Every (vulnerable version, advisory) reachable from root_id, with the dependency path to it.

    Sorted by depth, so direct exposure comes first.
    """
    found = []
    for version_id, path in dependency_paths(store, root_id, lockfile_doc_id, max_depth=max_depth).items():
        for edge in store.neighbors(version_id, relation=HAS_VULNERABILITY, direction="out"):
            vuln_id = edge["entity_id"]
            if vulnerability_ids is not None and vuln_id not in vulnerability_ids:
                continue
            found.append({"vulnerability_id": vuln_id, "version_id": version_id, "path": path, "depth": len(path) - 1})
    return sorted(found, key=lambda f: (f["depth"], f["vulnerability_id"], f["version_id"]))


def exposed_lockfiles(store: GraphStore, vulnerability_id: str) -> dict[str, list[str]]:
    """lockfile doc id -> affected version ids in it, for one advisory."""
    by_lockfile: dict[str, list[str]] = {}
    for edge in store.neighbors(vulnerability_id, relation=HAS_VULNERABILITY, direction="in"):
        for doc_id in edge["properties"].get("lockfile_doc_ids", ()):
            by_lockfile.setdefault(doc_id, []).append(edge["entity_id"])
    return {doc_id: sorted(versions) for doc_id, versions in sorted(by_lockfile.items())}
