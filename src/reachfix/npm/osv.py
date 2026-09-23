"""OSV.dev API access and record helpers.

Two calls, used by scripts/fetch_osv.py for the corpus and by OsvClient for
uploaded lockfiles:
1. POST /v1/querybatch with (name, version) pairs, 1000 per request. This
   returns matching advisory ids and `modified` times only, paginated per
   query.
2. GET /v1/vulns/{id} for the full record (`affected` ranges, `details`).
   Records are cached on disk and re-downloaded only when OSV reports a
   newer `modified` time.
"""

import json
import os
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from .http import make_session, request_json

OSV_API = "https://api.osv.dev/v1"
BATCH_SIZE = 1000  # OSV's documented querybatch limit
WORKERS = 8

Matches = dict[tuple[str, str], dict[str, str]]  # (name, version) -> {vuln_id: modified}


def normalize_modified(ts: str) -> str:
    """Truncate an OSV `modified` timestamp to microseconds.

    /v1/querybatch reports microseconds ("…:10.642592Z") but /v1/vulns/{id}
    reports nanoseconds ("…:10.642592133Z") for the same instant, so the raw
    strings never compare equal.
    """
    body = ts.rstrip("Z")
    if "." in body:
        whole, frac = body.split(".", 1)
        body = f"{whole}.{frac[:6].ljust(6, '0')}"
    return body + "Z"


def query_package(name: str, version: str, page_token: str | None = None) -> dict:
    query = {"package": {"name": name, "ecosystem": "npm"}, "version": version}
    if page_token:
        query["page_token"] = page_token
    return query


def batch_query(session: requests.Session, name_versions: list[tuple[str, str]],
                progress: Callable[[int, int, int], None] | None = None) -> Matches:
    """(name, version) -> {vuln_id: modified} for every queried version with at least one advisory.

    progress(start, size, total), if given, is called before each batch.
    """
    matches: Matches = {}
    for start in range(0, len(name_versions), BATCH_SIZE):
        chunk = name_versions[start:start + BATCH_SIZE]
        if progress:
            progress(start, len(chunk), len(name_versions))
        pending = [(nv, None) for nv in chunk]
        while pending:
            body = {"queries": [query_package(n, v, tok) for (n, v), tok in pending]}
            results = request_json(session, "POST", f"{OSV_API}/querybatch", json=body)["results"]
            next_pending = []
            for ((name, version), _), result in zip(pending, results):
                for vuln in result.get("vulns", []):
                    matches.setdefault((name, version), {})[vuln["id"]] = vuln["modified"]
                if result.get("next_page_token"):
                    next_pending.append(((name, version), result["next_page_token"]))
            pending = next_pending
    return matches


def fetch_record(session: requests.Session, cache_dir: Path, vuln_id: str, modified: str | None,
                 refresh: bool = False) -> tuple[dict, bool]:
    """(record, downloaded). A cached record is reused unless OSV's `modified` is different, or refresh."""
    local_path = cache_dir / f"{vuln_id}.json"
    if local_path.exists() and not refresh:
        cached = json.loads(local_path.read_text(encoding="utf-8"))
        if modified is None or normalize_modified(cached.get("modified", "")) == normalize_modified(modified):
            return cached, False
    record = request_json(session, "GET", f"{OSV_API}/vulns/{vuln_id}")
    # Write then rename, so a concurrent reader never sees a half-written file.
    tmp_path = local_path.with_name(f"{local_path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    os.replace(tmp_path, local_path)
    return record, True


def fetch_records(session: requests.Session, cache_dir: Path, wanted: dict[str, str | None],
                  refresh: bool = False) -> list[tuple[str, dict, bool]]:
    """[(vuln_id, record, downloaded)] for {vuln_id: modified}, fetched in parallel, sorted by id."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(lambda item: (item[0], *fetch_record(session, cache_dir, *item, refresh)),
                             sorted(wanted.items())))


class OsvClient:
    """Live OSV lookups for an uploaded lockfile, with records cached under `cache_dir`.

    The cache is separate from the corpus's data/raw/osv/vulns, so an
    upload never changes what the build scripts read.
    """

    def __init__(self, cache_dir: Path, session: requests.Session | None = None):
        self.cache_dir = cache_dir
        self.session = session or make_session()

    def lookup(self, name_versions: Iterable[tuple[str, str]]) -> tuple[dict[tuple[str, str], set[str]], dict[str, dict]]:
        """(OSV's matches: (name, version) -> advisory ids, the full records of every matched advisory)."""
        matches = batch_query(self.session, sorted(set(name_versions)))
        wanted = {vuln_id: modified for vulns in matches.values() for vuln_id, modified in vulns.items()}
        records = {vuln_id: record for vuln_id, record, _ in fetch_records(self.session, self.cache_dir, wanted)}
        return {nv: set(vulns) for nv, vulns in matches.items()}, records
