"""Chunk-content-keyed cache for extraction results.

Keeps development re-runs (schema tweaks, prompt tweaks, re-processing the
same corpus) from re-spending LLM tokens on chunks whose extraction inputs
haven't changed. Keyed on chunk text + model + schema version rather than
just chunk_id, so a prompt/model/schema change invalidates the cache but an
unrelated code change doesn't.
"""

import hashlib
import json
from pathlib import Path


def make_cache_key(chunk_id: str, chunk_text: str, *, model_name: str, schema_version: int) -> str:
    payload = f"{chunk_id}|{model_name}|v{schema_version}|{chunk_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_path(cache_root: Path, key: str) -> Path:
    return cache_root / f"{key}.json"


def read_cache(cache_root: Path, key: str) -> list[dict] | None:
    path = cache_path(cache_root, key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(cache_root: Path, key: str, edges: list[dict]) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path(cache_root, key).write_text(json.dumps(edges), encoding="utf-8")
