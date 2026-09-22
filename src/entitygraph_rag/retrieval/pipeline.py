"""Orchestrate chunk embedding with caching.

Mirrors extraction/pipeline.py's cache-then-call shape, but batches
whatever chunks are left uncached into fewer, larger embed_content calls
(see EMBED_BATCH_SIZE) rather than one call per chunk — embeddings, unlike
structured triple extraction, batch cleanly.
"""

from pathlib import Path

import numpy as np
from google import genai

from . import cache
from .embeddings import embed_texts

EMBED_BATCH_SIZE = 100


def embed_chunks(
    chunks: list[dict],
    *,
    client: genai.Client,
    model_name: str,
    output_dimensionality: int,
    cache_root: Path,
) -> tuple[list[str], np.ndarray]:
    """Return (chunk_ids, vectors) for every chunk, embedding only what's not cached."""
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    vectors_by_id: dict[str, list[float]] = {}
    to_embed: list[dict] = []

    for chunk in chunks:
        key = cache.make_cache_key(
            chunk["chunk_id"], chunk["text"], model_name=model_name, output_dimensionality=output_dimensionality
        )
        cached = cache.read_cache(cache_root, key)
        if cached is not None:
            vectors_by_id[chunk["chunk_id"]] = cached
        else:
            to_embed.append(chunk)

    for i in range(0, len(to_embed), EMBED_BATCH_SIZE):
        batch = to_embed[i : i + EMBED_BATCH_SIZE]
        embedded = embed_texts(
            client,
            [chunk["text"] for chunk in batch],
            task_type="RETRIEVAL_DOCUMENT",
            model_name=model_name,
            output_dimensionality=output_dimensionality,
        )
        for chunk, vector in zip(batch, embedded):
            vectors_by_id[chunk["chunk_id"]] = vector
            key = cache.make_cache_key(
                chunk["chunk_id"], chunk["text"], model_name=model_name, output_dimensionality=output_dimensionality
            )
            cache.write_cache(cache_root, key, vector)

    matrix = np.array([vectors_by_id[chunk_id] for chunk_id in chunk_ids], dtype=np.float32)
    return chunk_ids, matrix
