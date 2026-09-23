"""Fetch every-version manifests for the packages remediation needs (Phase 9).

The trimmed packuments from scripts/fetch_npm_metadata.py keep manifests
only for corpus versions. A remediation plan also asks what *newer*
versions declare ("which glob release stops pinning minimatch to ^3?"),
and which versions are deprecated. Which packages those questions touch
is only known by planning, so this loops: plan every vulnerable copy in
every lockfile, fetch the packages the plans found missing, and repeat
until nothing is missing.

Output (gitignored): data/raw/npm/releases/<name>.json (scoped "/" -> "__",
see entitygraph_rag.npm.registry.trim_releases) and
data/raw/npm/releases_manifest.jsonl. Packages already on disk are not
re-fetched unless --refresh is given.

Usage:
    uv run python scripts/fetch_release_metadata.py [--refresh]
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from entitygraph_rag.graph import NetworkXGraphStore
from entitygraph_rag.npm.corpus import read_jsonl
from entitygraph_rag.npm.http import make_session, request_json
from entitygraph_rag.npm.registry import packument_url, trim_releases
from entitygraph_rag.npm.releases import Releases
from entitygraph_rag.npm.remediation import plan_fix, vulnerable_copies

ROOT = Path(__file__).resolve().parent.parent
DEPGRAPH_DIR = ROOT / "data" / "processed" / "depgraph"
NPM_DIR = ROOT / "data" / "raw" / "npm"
PACKUMENT_DIR = NPM_DIR / "packuments"
RELEASE_DIR = NPM_DIR / "releases"
MANIFEST_PATH = NPM_DIR / "releases_manifest.jsonl"
WORKERS = 8
MAX_ROUNDS = 10

session = make_session()
session.headers.update({"Accept": "application/json"})


def local_path_for(name: str) -> Path:
    return RELEASE_DIR / f"{name.replace('/', '__')}.json"


def fetch_one(name: str) -> dict:
    url = packument_url(name)
    trimmed = trim_releases(request_json(session, "GET", url))
    path = local_path_for(name)
    path.write_text(json.dumps(trimmed, separators=(",", ":")), encoding="utf-8")
    return {"doc_id": f"npm-registry:{name}", "name": name, "source_url": url,
            "local_path": path.relative_to(ROOT).as_posix(), "versions": len(trimmed["versions"]),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def missing_after_planning(store, copies) -> set[str]:
    releases = Releases.from_dirs(PACKUMENT_DIR, RELEASE_DIR)
    for lockfile, version in copies:
        plan_fix(store, releases, lockfile, version)
    return releases.missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="Re-download every release file")
    args = parser.parse_args()

    if not (DEPGRAPH_DIR / "graph.pkl").exists():
        raise SystemExit("No graph; run scripts/build_depgraph.py first.")
    store = NetworkXGraphStore.from_file(DEPGRAPH_DIR / "graph.pkl")
    copies = vulnerable_copies(read_jsonl(DEPGRAPH_DIR / "vulnerability_edges.jsonl"))
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {r["name"]: r for r in read_jsonl(MANIFEST_PATH)} if MANIFEST_PATH.exists() else {}
    if args.refresh:
        for path in RELEASE_DIR.glob("*.json"):
            path.unlink()
        manifest = {}
    print(f"{len(copies)} (lockfile, vulnerable version) pairs to plan")

    failures: dict[str, str] = {}
    for round_no in range(1, MAX_ROUNDS + 1):
        todo = sorted(missing_after_planning(store, copies) - set(failures))
        print(f"round {round_no}: {len(todo)} packages missing", flush=True)
        if not todo:
            break
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_one, n): n for n in todo}
            for future in as_completed(futures):
                try:
                    manifest[futures[future]] = future.result()
                except requests.RequestException as exc:
                    failures[futures[future]] = str(exc)
    else:
        print(f"stopped after {MAX_ROUNDS} rounds with packages still missing")

    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        for name in sorted(manifest):
            f.write(json.dumps(manifest[name]) + "\n")
    print(f"\nDone. {len(manifest)} release files in {RELEASE_DIR.relative_to(ROOT).as_posix()}")
    if failures:
        print(f"Failed ({len(failures)}):")
        for name, err in sorted(failures.items()):
            print(f"  {name}: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
