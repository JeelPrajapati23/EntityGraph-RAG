"""Plain semantic search: embed a query, search the index, return chunk records."""

from google import genai

from .embeddings import DEFAULT_EMBEDDING_MODEL, DEFAULT_OUTPUT_DIMENSIONALITY, embed_texts
from .index import VectorIndex


def semantic_search(
    query: str,
    *,
    index: VectorIndex,
    chunks_by_id: dict[str, dict],
    client: genai.Client,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    output_dimensionality: int = DEFAULT_OUTPUT_DIMENSIONALITY,
    top_k: int = 5,
) -> list[dict]:
    [query_vector] = embed_texts(
        client,
        [query],
        task_type="RETRIEVAL_QUERY",
        model_name=model_name,
        output_dimensionality=output_dimensionality,
    )

    results = []
    for chunk_id, score in index.search(query_vector, top_k=top_k):
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        results.append({**chunk, "score": score})
    return results
