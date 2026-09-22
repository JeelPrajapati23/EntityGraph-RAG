"""Semantic search: embed a query, search the index, return chunk records.

candidate_chunk_ids, when given, scopes the search to that subset instead
of the full index — this is what the graph-guided-hybrid router path uses
to search only chunks tied to entities the query mentions (see
router/dispatch.py).
"""

from huggingface_hub import InferenceClient

from .embeddings import DEFAULT_EMBEDDING_MODEL, embed_texts
from .index import VectorIndex


def semantic_search(
    query: str,
    *,
    index: VectorIndex,
    chunks_by_id: dict[str, dict],
    client: InferenceClient,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 5,
    candidate_chunk_ids: set[str] | None = None,
) -> list[dict]:
    [query_vector] = embed_texts(client, [query], task_type="RETRIEVAL_QUERY", model_name=model_name)

    if candidate_chunk_ids is not None:
        hits = index.search_subset(query_vector, candidate_chunk_ids, top_k=top_k)
    else:
        hits = index.search(query_vector, top_k=top_k)

    results = []
    for chunk_id, score in hits:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        results.append({**chunk, "score": score})
    return results
