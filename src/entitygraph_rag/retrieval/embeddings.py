"""Thin Gemini embedding wrapper.

Unlike structured triple extraction (one call per chunk, since the JSON
schema is per-chunk), embeddings batch cleanly: embed_content accepts a
list of texts in one call, so the caller (pipeline.py) batches whatever
chunks are left after a cache lookup instead of calling once per chunk.
"""

from google import genai
from google.genai import types

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_OUTPUT_DIMENSIONALITY = 768


def embed_texts(
    client: genai.Client,
    texts: list[str],
    *,
    task_type: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    output_dimensionality: int = DEFAULT_OUTPUT_DIMENSIONALITY,
) -> list[list[float]]:
    """Embed a batch of texts.

    task_type is "RETRIEVAL_DOCUMENT" for chunks being indexed, or
    "RETRIEVAL_QUERY" for a search query — Gemini's embedding models are
    trained asymmetrically for retrieval, so query/document embeddings
    aren't interchangeable and the wrong task_type measurably hurts
    ranking quality.
    """
    response = client.models.embed_content(
        model=model_name,
        contents=texts,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=output_dimensionality),
    )
    return [embedding.values for embedding in response.embeddings]
