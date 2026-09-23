"""Resolve a date-pinned package-lock.json for each corpus root in config/projects.yaml.

For each root this runs, in an empty scratch project:
    npm install <name>@<version> --package-lock-only --before=<resolve_before>
        --ignore-scripts --legacy-peer-deps --no-audit --no-fund
--package-lock-only writes the lockfile without downloading tarballs.
--before resolves every range to the newest version published before
that date, which keeps the historical vulnerable transitive dependencies
in the tree (see docs/dataset.md). Needs Node/npm on PATH.

Output: data/raw/lockfiles/<slug>/{package.json,package-lock.json} and
data/raw/lockfiles/manifest.jsonl (gitignored, acquired data).
Roots that already have a lockfile are skipped unless --refresh is given.

Usage:
    uv run python scripts/fetch_lockfiles.py [--projects express,axios] [--refresh]
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from reachfix.npm.lockfile import installed_packages, load_lockfile
from reachfix.npm.projects import Project, load_projects
from reachfix.npm.registry import packument_url

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / "lockfiles"
NPM_FLAGS = ["--package-lock-only", "--ignore-scripts", "--legacy-peer-deps", "--no-audit", "--no-fund",
             # npm's default 5-minute fetch timeout let one stalled registry socket hang a whole root.
             "--fetch-timeout=60000", "--fetch-retries=4"]
NPM_TIMEOUT_SECONDS = 900

# The scratch project that the root gets installed into. Its own name never
# reaches the graph: the lockfile's "" entry is skipped when parsing.
SCRATCH_PACKAGE_JSON = {"name": "depgraph-scratch", "version": "0.0.0", "private": True}


def npm_executable() -> str:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm not found on PATH. Install Node.js (npm 7+ for lockfileVersion 2/3).")
    return npm


def resolve_lockfile(npm: str, project: Project, dest_dir: Path) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "package-lock.json").unlink(missing_ok=True)
    (dest_dir / "package.json").write_text(json.dumps(SCRATCH_PACKAGE_JSON, indent=2) + "\n", encoding="utf-8")

    command = [npm, "install", project.spec, f"--before={project.resolve_before}", *NPM_FLAGS]
    result = subprocess.run(
        command, cwd=dest_dir, capture_output=True, text=True, encoding="utf-8", timeout=NPM_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RuntimeError(f"npm exited {result.returncode}:\n{result.stderr[-2000:]}")

    lock_path = dest_dir / "package-lock.json"
    packages = installed_packages(load_lockfile(lock_path))
    return {
        "doc_id": f"lockfile:npm:{project.spec}",
        "ecosystem": "npm",
        "root_name": project.name,
        "root_version": project.version,
        "resolve_before": project.resolve_before,
        "command": " ".join(["npm", *command[1:]]),
        "source_url": packument_url(project.name),
        "local_path": lock_path.relative_to(ROOT).as_posix(),
        "package_count": len(packages),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {r["doc_id"]: r for r in records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--projects", type=str, default=None, help="Comma-separated root names (default: all)")
    parser.add_argument("--refresh", action="store_true", help="Re-resolve roots that already have a lockfile")
    args = parser.parse_args()

    projects = load_projects()
    if args.projects:
        wanted = {p.strip() for p in args.projects.split(",")}
        projects = [p for p in projects if p.name in wanted]

    npm = npm_executable()
    npm_version = subprocess.run([npm, "--version"], capture_output=True, text=True).stdout.strip()
    print(f"npm {npm_version}; resolving {len(projects)} roots...")

    manifest_path = OUT_DIR / "manifest.jsonl"
    manifest = load_manifest(manifest_path)
    failures = []

    for project in projects:
        doc_id = f"lockfile:npm:{project.spec}"
        dest_dir = OUT_DIR / project.slug
        if not args.refresh and doc_id in manifest and (dest_dir / "package-lock.json").exists():
            print(f"  = {project.spec}: already resolved ({manifest[doc_id]['package_count']} packages), skipping")
            continue

        print(f"  {project.spec} (before {project.resolve_before})...", flush=True)
        try:
            record = resolve_lockfile(npm, project, dest_dir)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            print(f"    ! failed: {exc}")
            failures.append(project.spec)
            continue
        record["npm_version"] = npm_version
        manifest[doc_id] = record
        print(f"    {record['package_count']} packages -> {record['local_path']}")

        # Rewrite after every root so an interrupted run keeps its progress.
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as f:
            for r in manifest.values():
                f.write(json.dumps(r) + "\n")

    print(f"\nDone. {len(manifest)} lockfiles recorded in {manifest_path.relative_to(ROOT).as_posix()}")
    if failures:
        print(f"Failed: {', '.join(failures)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
