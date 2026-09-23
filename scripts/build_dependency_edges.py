"""Rebuild logical DEPENDS_ON edges from the resolved lockfiles.

For every dependency each installed package declares, finds the copy Node
would load (own node_modules first, then each enclosing one; see
entitygraph_rag.npm.dependencies). Edges keep the declared range and
dependency type, list every lockfile they occur in, and are checked against
the registry's declared dependencies for that version (from
scripts/fetch_npm_metadata.py's trimmed packuments).

Output (gitignored), fully rewritten each run:
    data/processed/depgraph/dependency_edges.jsonl
    data/processed/depgraph/unresolved_dependencies.jsonl  (deps nothing in the tree satisfies)

Usage:
    uv run python scripts/build_dependency_edges.py
"""

import argparse
import json
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path

from entitygraph_rag.npm.corpus import read_jsonl
from entitygraph_rag.npm.dependencies import build_edges, registry_only_declarations, resolve_dependencies
from entitygraph_rag.npm.lockfile import installed_packages, load_lockfile

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE_MANIFEST = ROOT / "data" / "raw" / "lockfiles" / "manifest.jsonl"
PACKUMENT_DIR = ROOT / "data" / "raw" / "npm" / "packuments"
OUT_DIR = ROOT / "data" / "processed" / "depgraph"


@cache
def load_packument(name: str) -> dict | None:
    path = PACKUMENT_DIR / f"{name.replace('/', '__')}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def registry_version(name: str, version: str) -> dict | None:
    packument = load_packument(name)
    return packument["versions"].get(version) if packument else None


def unreachable_count(deps, root_path: str, all_paths: set[str]) -> int:
    """Installed packages not reachable from the corpus root by following resolved deps."""
    children = defaultdict(set)
    for dep in deps:
        if dep.target is not None:
            children[dep.source.path].add(dep.target.path)
    seen, stack = {root_path}, [root_path]
    while stack:
        for child in children[stack.pop()] - seen:
            seen.add(child)
            stack.append(child)
    return len(all_paths - seen)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    if not LOCKFILE_MANIFEST.exists():
        raise SystemExit("No lockfile manifest; run scripts/fetch_lockfiles.py first.")
    if not PACKUMENT_DIR.exists():
        print("  ! no registry packuments; every edge's registry_check will be no_registry_data")

    lockfile_deps = {}
    all_packages = []
    for record in read_jsonl(LOCKFILE_MANIFEST):
        lock = load_lockfile(ROOT / record["local_path"])
        packages = installed_packages(lock)
        deps = resolve_dependencies(lock)
        lockfile_deps[record["doc_id"]] = deps
        all_packages.extend(packages)

        root_path = f"node_modules/{record['root_name']}"
        # One source version resolving the same dep to different versions within one tree.
        targets = defaultdict(set)
        for dep in deps:
            if dep.target is not None:
                targets[(dep.source.name, dep.source.version, dep.dep_name)].add(dep.target.version)
        split = sum(len(v) > 1 for v in targets.values())
        print(f"  {record['root_name']}@{record['root_version']}: {len(packages)} packages, {len(deps)} declared deps, "
              f"{sum(d.target is None for d in deps)} unresolved, "
              f"{unreachable_count(deps, root_path, {p.path for p in packages})} unreachable from root, "
              f"{split} split resolutions")

    edges, unresolved = build_edges(lockfile_deps, registry_version)
    unique_packages = {(p.name, p.version): p for p in all_packages}.values()
    registry_only = registry_only_declarations(unique_packages, registry_version)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "dependency_edges.jsonl", edges)
    write_jsonl(OUT_DIR / "unresolved_dependencies.jsonl", unresolved)

    by_type = Counter(e["dependency_type"] for e in edges)
    checks = Counter(e["registry_check"] for e in edges)
    peer_optional = sum(u["peer_optional"] for u in unresolved)
    print(f"\nDone. {len(edges)} version-level edges ({dict(by_type)}) -> "
          f"{(OUT_DIR / 'dependency_edges.jsonl').relative_to(ROOT).as_posix()}")
    print(f"  registry cross-check: {dict(checks)}")
    unsatisfied = [e for e in edges if not e["range_satisfied"]]
    print(f"  resolved version outside its declared range: {len(unsatisfied)}")
    for e in unsatisfied:
        print(f"    {e['from_name']}@{e['from_version']} -> {e['to_name']}@{e['to_version']} "
              f"({e['dependency_type']} {e['version_range']!r})")
    print(f"  registry declares {len(registry_only)} deps that the lockfiles don't list")
    print(f"  {len(unresolved)} unresolved ({peer_optional} optional peers) -> "
          f"{(OUT_DIR / 'unresolved_dependencies.jsonl').relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
