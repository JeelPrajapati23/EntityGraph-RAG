"""The corpus as a set of package versions, read through the lockfile manifest."""

import json
from collections import defaultdict
from pathlib import Path

from .lockfile import installed_packages, load_lockfile


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def corpus_name_versions(lockfile_manifest: Path, root: Path) -> dict[tuple[str, str], set[str]]:
    """(name, version) -> doc_ids of the lockfiles it is installed in, across the whole corpus."""
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in read_jsonl(lockfile_manifest):
        lock = load_lockfile(root / record["local_path"])
        for pkg in installed_packages(lock):
            found[(pkg.name, pkg.version)].add(record["doc_id"])
    return dict(found)


def versions_by_name(name_versions) -> dict[str, set[str]]:
    by_name: dict[str, set[str]] = defaultdict(set)
    for name, version in name_versions:
        by_name[name].add(version)
    return dict(by_name)
