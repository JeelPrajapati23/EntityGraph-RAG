"""Plan a fix for every vulnerable version in every lockfile (Phase 9).

For each (lockfile, vulnerable version) pair, runs npm.remediation.plan_fix
against the graph and the release metadata, and writes:
- data/processed/depgraph/remediation.jsonl: one plan per pair;
- data/processed/depgraph/releases.json: the release metadata those plans
  read (versions, declared ranges, deprecation), which is what the router
  loads to plan fixes at query time.

Offline. Fails if a plan needed metadata that isn't on disk; run
scripts/fetch_release_metadata.py first.

Usage:
    uv run python scripts/build_remediation.py
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from reachfix.graph import NetworkXGraphStore
from reachfix.npm.corpus import read_jsonl
from reachfix.npm.releases import Releases
from reachfix.npm.remediation import actions, is_resolved, plan_fix, vulnerable_copies

ROOT = Path(__file__).resolve().parent.parent
DEPGRAPH_DIR = ROOT / "data" / "processed" / "depgraph"
NPM_DIR = ROOT / "data" / "raw" / "npm"
DEMOS = [("lockfile:npm:axios@0.21.1", "npm:follow-redirects@1.13.1"),
         ("lockfile:npm:mocha@8.4.0", "npm:minimatch@3.0.4")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    store = NetworkXGraphStore.from_file(DEPGRAPH_DIR / "graph.pkl")
    releases = Releases.from_dirs(NPM_DIR / "packuments", NPM_DIR / "releases")
    copies = vulnerable_copies(read_jsonl(DEPGRAPH_DIR / "vulnerability_edges.jsonl"))
    plans = [plan_fix(store, releases, lockfile, version) for lockfile, version in copies]
    if releases.missing:
        raise SystemExit(f"release metadata missing for {len(releases.missing)} packages "
                         f"(e.g. {sorted(releases.missing)[:5]}); run scripts/fetch_release_metadata.py")

    with (DEPGRAPH_DIR / "remediation.jsonl").open("w", encoding="utf-8") as f:
        for plan in plans:
            f.write(json.dumps(plan) + "\n")
    releases.save(DEPGRAPH_DIR / "releases.json")

    status = Counter(p["status"] for p in plans)
    blocked = [p for p in plans if p["status"] == "blocked"]
    print(f"{len(plans)} plans -> data/processed/depgraph/remediation.jsonl; "
          f"release metadata for {len(releases.touched)} packages -> releases.json")
    for s, n in status.most_common():
        print(f"  {s:13} {n}")
    no_fix = [p for p in plans if p["status"] == "no_fix"]
    print(f"  blocked, but every blocker has an upgrade path: {sum(map(is_resolved, blocked))} of {len(blocked)}")
    print(f"  no fix, but every dependent can upgrade to a release that drops it: {sum(map(is_resolved, no_fix))} of {len(no_fix)}")
    print(f"  target still hit by another known advisory: {sum(bool(p.get('still_affected_by')) for p in plans)}")
    print(f"  target above the lowest safe version (a dependent's range or a cleaner release): "
          f"{sum(p.get('target_version') not in (None, p['lowest_safe_version']) for p in plans)}")

    by_pair = {(p["lockfile_doc_id"], p["version_id"]): p for p in plans}
    for pair in DEMOS:
        if pair in by_pair:
            plan = by_pair[pair]
            print(f"\n{pair[1].removeprefix('npm:')} in {pair[0]} [{', '.join(plan['advisories'])}]: {plan['status']}")
            for line in actions(plan):
                print(f"  {line}")


if __name__ == "__main__":
    main()
