"""Thin Hugging Face Inference API wrapper for chunk/query embeddings.

Unlike Gemini's asymmetric embedding API (separate RETRIEVAL_QUERY/
RETRIEVAL_DOCUMENT task types), HF's plain feature-extraction endpoint has
no query/document distinction — task_type is accepted for interface
compatibility with existing call sites (search.py, pipeline.py) and
otherwise unused.
"""

import os

import numpy as np
from huggingface_hub import InferenceClient

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_OUTPUT_DIMENSIONALITY = 384  # all-MiniLM-L6-v2's native dimension; used for cache-key namespacing only


def build_embedding_client(api_key: str | None = None) -> InferenceClient:
    api_key = api_key or os.environ.get("HF_TOKEN")
    if not api_key:
        raise RuntimeError("HF_TOKEN is not set (check .env)")
    return InferenceClient(token=api_key)


def embed_texts(
    client: InferenceClient,
    texts: list[str],
    *,
    task_type: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> list[list[float]]:
    """Embed a batch of texts, one Inference API call per text.

    A 2D per-token result (a model without built-in pooling) is mean-pooled
    into a single vector; sentence-transformers models like the default
    already return one pooled vector per input.
    """
    vectors = []
    for text in texts:
        result = np.asarray(client.feature_extraction(text, model=model_name))
        if result.ndim == 2:
            result = result.mean(axis=0)
        vectors.append(result.tolist())
    return vectors
