"""Fetch release metadata from the npm registry at scan time, for remediation of uploaded lockfiles.

releases.json only covers the packages the corpus's own plans touched. An
upload's plans can need others (a vulnerable package outside the corpus,
or a dependent to upgrade), so depgraph/scan.py asks RegistryClient for
whatever a planning round found missing, then plans again.

Uses the registry's abbreviated packuments (Accept:
application/vnd.npm.install-v1+json). They keep every version's
dependencies and deprecation, so registry.trim_releases gives the same
result as from a full packument, at about half the download size.

Cached per package under `cache_dir`, apart from the corpus's
data/raw/npm/releases, and re-fetched after `ttl` since new releases
appear.
"""

import json
import os
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .http import make_session, request_json
from .registry import packument_url, trim_releases

ABBREVIATED = "application/vnd.npm.install-v1+json"
CACHE_TTL = timedelta(days=1)
WORKERS = 8


def release_entry(trimmed: dict) -> dict:
    """A trim_releases result in the shape Releases.packages holds."""
    return {"versions": list(trimmed["versions"]), "manifests": trimmed["versions"], "complete": True}


class RegistryClient:
    def __init__(self, cache_dir: Path, session: requests.Session | None = None, ttl: timedelta = CACHE_TTL,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.cache_dir = cache_dir
        self.session = session or make_session()
        self.ttl = ttl
        self.now = now

    def _path(self, name: str) -> Path:
        return self.cache_dir / f"{name.replace('/', '__')}.json"

    def _cached(self, name: str) -> dict | None:
        path = self._path(name)
        if not path.exists():
            return None
        cached = json.loads(path.read_text(encoding="utf-8"))
        if self.now() - datetime.fromisoformat(cached["fetched_at"]) > self.ttl:
            return None
        return cached["release"]

    def _fetch_one(self, name: str) -> dict:
        cached = self._cached(name)
        if cached is not None:
            return cached
        trimmed = trim_releases(request_json(self.session, "GET", packument_url(name),
                                             headers={"Accept": ABBREVIATED}))
        # Write then rename, so a concurrent scan never reads a half-written file.
        path = self._path(name)
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps({"fetched_at": self.now().isoformat(timespec="seconds"), "release": trimmed},
                                       separators=(",", ":")), encoding="utf-8")
        os.replace(tmp_path, path)
        return trimmed

    def fetch(self, names: Iterable[str]) -> tuple[dict[str, dict], dict[str, str]]:
        """({name: Releases package entry}, {name: error}) for each requested package, fetched in parallel."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        def one(name: str) -> tuple[str, dict | None, str | None]:
            try:
                return name, release_entry(self._fetch_one(name)), None
            except (requests.RequestException, ValueError, KeyError) as e:
                return name, None, f"{e.__class__.__name__}: {e}"

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(one, sorted(set(names))))
        return ({n: entry for n, entry, _ in results if entry is not None},
                {n: err for n, _, err in results if err is not None})
