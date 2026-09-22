"""Chunk-content-keyed cache for embedding vectors.

Same rationale as extraction/cache.py: keeps development re-runs from
re-spending API calls on chunks whose text hasn't changed. Kept as its own
small module (rather than sharing extraction's) since the cache key here is
built from model name + output dimensionality instead of schema version —
the two caches key on genuinely different things.
"""

import hashlib
import json
from pathlib import Path


def make_cache_key(chunk_id: str, chunk_text: str, *, model_name: str, output_dimensionality: int) -> str:
    payload = f"{chunk_id}|{model_name}|{output_dimensionality}|{chunk_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_path(cache_root: Path, key: str) -> Path:
    return cache_root / f"{key}.json"


def read_cache(cache_root: Path, key: str) -> list[float] | None:
    path = cache_path(cache_root, key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(cache_root: Path, key: str, vector: list[float]) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path(cache_root, key).write_text(json.dumps(vector), encoding="utf-8")
