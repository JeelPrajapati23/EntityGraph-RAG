"""Fetch npm registry metadata for every package name in the resolved lockfiles.

Downloads each full packument from registry.npmjs.org/<name> and keeps a
trimmed copy (see entitygraph_rag.npm.registry.trim_packument):
maintainer usernames (emails dropped), the publish-time map, all version
strings, and license / deprecation / declared dependencies for the
versions that appear in a corpus tree. Full packuments can be many MB and
are never written to disk.

The declared dependencies give Phase 5 an independent registry source to
cross-check the lockfile's DEPENDS_ON edges against.

Output (gitignored): data/raw/npm/packuments/<name>.json (scoped "/" -> "__")
and data/raw/npm/manifest.jsonl. A package already on disk with every
wanted version is skipped unless --refresh is given.

Usage:
    uv run python scripts/fetch_npm_metadata.py [--refresh]
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from entitygraph_rag.npm.corpus import corpus_name_versions, read_jsonl, versions_by_name
from entitygraph_rag.npm.http import make_session, request_json
from entitygraph_rag.npm.registry import packument_url, trim_packument

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE_MANIFEST = ROOT / "data" / "raw" / "lockfiles" / "manifest.jsonl"
OUT_DIR = ROOT / "data" / "raw" / "npm"
PACKUMENT_DIR = OUT_DIR / "packuments"

# Modest concurrency: the public registry is CDN-backed but not ours to hammer.
WORKERS = 8

session = make_session()
session.headers.update({"Accept": "application/json"})


def local_path_for(name: str) -> Path:
    return PACKUMENT_DIR / f"{name.replace('/', '__')}.json"


def is_current(name: str, wanted_versions: set[str]) -> bool:
    path = local_path_for(name)
    if not path.exists():
        return False
    cached = json.loads(path.read_text(encoding="utf-8"))
    return wanted_versions <= set(cached["versions"])


def fetch_one(name: str, wanted_versions: set[str]) -> dict:
    url = packument_url(name)
    trimmed = trim_packument(request_json(session, "GET", url), wanted_versions)
    path = local_path_for(name)
    path.write_text(json.dumps(trimmed, indent=1), encoding="utf-8")
    return {
        "doc_id": f"npm-registry:{name}",
        "name": name,
        "source_url": url,
        "local_path": path.relative_to(ROOT).as_posix(),
        "versions_kept": sorted(trimmed["versions"]),
        "missing_versions": sorted(v for v, m in trimmed["versions"].items() if m.get("missing")),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="Re-download every packument")
    args = parser.parse_args()

    if not LOCKFILE_MANIFEST.exists():
        raise SystemExit("No lockfile manifest; run scripts/fetch_lockfiles.py first.")

    wanted = versions_by_name(corpus_name_versions(LOCKFILE_MANIFEST, ROOT))
    manifest_path = OUT_DIR / "manifest.jsonl"
    manifest = {r["name"]: r for r in read_jsonl(manifest_path)} if manifest_path.exists() else {}

    todo = {n: v for n, v in wanted.items() if args.refresh or n not in manifest or not is_current(n, v)}
    print(f"{len(wanted)} package names in corpus; {len(todo)} to fetch, {len(wanted) - len(todo)} already current")

    PACKUMENT_DIR.mkdir(parents=True, exist_ok=True)
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, n, v): n for n, v in sorted(todo.items())}
        for done, future in enumerate(as_completed(futures), 1):
            name = futures[future]
            try:
                manifest[name] = future.result()
            except requests.RequestException as exc:
                failures[name] = str(exc)
            if done % 200 == 0 or done == len(futures):
                print(f"  {done}/{len(futures)}", flush=True)

    # Drop names no longer in any tree, e.g. after a root was removed from config/projects.yaml.
    records = [manifest[n] for n in sorted(manifest) if n in wanted]
    with manifest_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    missing = sum(len(r["missing_versions"]) for r in records)
    print(f"\nDone. {len(records)} packuments recorded in {manifest_path.relative_to(ROOT).as_posix()}"
          f" ({missing} tree versions no longer on the registry)")
    if failures:
        print(f"Failed ({len(failures)}):")
        for name, err in sorted(failures.items()):
            print(f"  {name}: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
