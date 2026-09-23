"""Fetch OSV.dev advisories for every package version in the resolved lockfiles.

Two steps:
1. POST /v1/querybatch with every unique (name, version) in the corpus,
   1000 queries per request. This returns matching advisory ids only.
2. GET /v1/vulns/{id} for each advisory to get the full record: structured
   `affected` ranges plus the free-text `details` that Phase 3's LLM
   extraction reads.

OSV's own package -> advisory matches are saved to package_vulns.jsonl.
They are not graph input (HAS_VULNERABILITY is derived by our own semver
matching, see schema/v2.yaml). They are kept as ground truth to check that
matcher against.

Output (gitignored): data/raw/osv/vulns/<id>.json, data/raw/osv/package_vulns.jsonl,
data/raw/osv/manifest.jsonl. An advisory already on disk is re-downloaded
only if OSV reports a newer `modified` time, or with --refresh.

Usage:
    uv run python scripts/fetch_osv.py [--refresh]
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from reachfix.npm.corpus import corpus_name_versions, read_jsonl
from reachfix.npm.http import make_session
from reachfix.npm.osv import OSV_API, batch_query, fetch_records

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE_MANIFEST = ROOT / "data" / "raw" / "lockfiles" / "manifest.jsonl"
OUT_DIR = ROOT / "data" / "raw" / "osv"
VULN_DIR = OUT_DIR / "vulns"

OSV_WEB = "https://osv.dev/vulnerability/"

session = make_session()


def progress(start: int, size: int, total: int) -> None:
    print(f"  querybatch {start + 1}-{start + size} of {total}...", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="Re-download every advisory")
    args = parser.parse_args()

    if not LOCKFILE_MANIFEST.exists():
        raise SystemExit("No lockfile manifest; run scripts/fetch_lockfiles.py first.")

    corpus = corpus_name_versions(LOCKFILE_MANIFEST, ROOT)
    name_versions = sorted(corpus)
    print(f"Querying OSV for {len(name_versions)} unique package versions...")
    matches = batch_query(session, name_versions, progress)

    wanted: dict[str, str] = {}
    for vulns in matches.values():
        wanted.update(vulns)
    print(f"{len(matches)} package versions match {len(wanted)} advisories; fetching records...")

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = fetch_records(session, VULN_DIR, wanted, args.refresh)

    manifest_path = OUT_DIR / "manifest.jsonl"
    previous = {r["doc_id"]: r for r in read_jsonl(manifest_path)} if manifest_path.exists() else {}
    manifest_records = []
    downloaded = 0
    for vuln_id, record, was_downloaded in results:
        downloaded += was_downloaded
        manifest_records.append(
            {
                "doc_id": vuln_id,
                "source_url": OSV_WEB + vuln_id,
                "api_url": f"{OSV_API}/vulns/{vuln_id}",
                "modified": record.get("modified"),
                "local_path": (VULN_DIR / f"{vuln_id}.json").relative_to(ROOT).as_posix(),
                # An unchanged advisory keeps the time it was actually downloaded.
                "fetched_at": fetched_at if was_downloaded else previous.get(vuln_id, {}).get("fetched_at", fetched_at),
            }
        )

    with manifest_path.open("w", encoding="utf-8") as f:
        for r in manifest_records:
            f.write(json.dumps(r) + "\n")
    with (OUT_DIR / "package_vulns.jsonl").open("w", encoding="utf-8") as f:
        for (name, version), vulns in sorted(matches.items()):
            f.write(json.dumps({"name": name, "version": version, "vuln_ids": sorted(vulns)}) + "\n")

    print(f"\nDone. {len(manifest_records)} advisories ({downloaded} downloaded, "
          f"{len(manifest_records) - downloaded} unchanged) -> {OUT_DIR.relative_to(ROOT).as_posix()}/")


if __name__ == "__main__":
    main()
