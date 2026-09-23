"""Embed long chunks as overlapping windows, search windows, return parent chunks.

The embedding model (all-MiniLM-L6-v2) reads at most 256 word-pieces, and
the HF endpoint silently truncates the rest. On the DepGraph corpus an
802-word chunk embeds identically (cosine 1.0) to its first 150 words. So a
chunk longer than that is split into windows of at most `max_words` words,
overlapping by `overlap`, for embedding only. Each window starts with
`prefix` (e.g. an advisory's summary and package names), so every window
says what it is about, even when its body never names the package.

The chunks themselves (the unit for extraction and citation) are unchanged.
Search runs over windows, then rolls hits up to their parent chunk, keeping
each chunk's best window score.
"""

from huggingface_hub import InferenceClient

from .embeddings import DEFAULT_EMBEDDING_MODEL, embed_texts
from .index import VectorIndex

WINDOW_SEPARATOR = "#w"
DEFAULT_WINDOW_WORDS = 110
DEFAULT_OVERLAP_WORDS = 20
OVERFETCH = 4  # windows fetched per requested chunk, since several windows can share a parent


def window_id(chunk_id: str, index: int) -> str:
    return f"{chunk_id}{WINDOW_SEPARATOR}{index}"


def parent_chunk_id(window: str) -> str:
    return window.rsplit(WINDOW_SEPARATOR, 1)[0]


def embedding_windows(
    chunk_id: str,
    text: str,
    *,
    prefix: str = "",
    max_words: int | None = DEFAULT_WINDOW_WORDS,
    overlap: int = DEFAULT_OVERLAP_WORDS,
) -> list[dict]:
    """[{chunk_id: window id, text: prefix + window body}] for one chunk. max_words=None: one window."""
    words = text.split()
    if max_words is None or len(words) <= max_words:
        bodies = [" ".join(words)]
    else:
        step = max_words - overlap
        if step <= 0:
            raise ValueError("overlap must be smaller than max_words")
        bodies = [" ".join(words[start:start + max_words])
                  for start in range(0, len(words) - overlap, step)]
    head = f"{prefix.strip()}\n" if prefix.strip() else ""
    return [{"chunk_id": window_id(chunk_id, i), "text": head + body} for i, body in enumerate(bodies)]


def rollup(hits: list[tuple[str, float]], top_k: int) -> list[tuple[str, float, str]]:
    """Window hits (best first) -> (parent chunk id, best score, best window id), one per parent."""
    best: dict[str, tuple[float, str]] = {}
    for window, score in hits:
        parent = parent_chunk_id(window)
        if parent not in best:
            best[parent] = (score, window)
    ranked = sorted(best.items(), key=lambda item: -item[1][0])
    return [(parent, score, window) for parent, (score, window) in ranked[:top_k]]


def search_chunks(
    query: str,
    *,
    index: VectorIndex,
    chunks_by_id: dict[str, dict],
    client: InferenceClient,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 5,
    candidate_chunk_ids: set[str] | None = None,
    query_vector: list[float] | None = None,
) -> list[dict]:
    """Top chunks for a query, over a window index: chunk fields plus `score` and `matched_window`.

    candidate_chunk_ids scopes the search to those parent chunks (the
    graph-guided route). query_vector skips the embedding call when the
    caller already has one.
    """
    if query_vector is None:
        [query_vector] = embed_texts(client, [query], task_type="RETRIEVAL_QUERY", model_name=model_name)
    k = top_k * OVERFETCH
    if candidate_chunk_ids is not None:
        windows = {w for w in index.chunk_ids if parent_chunk_id(w) in candidate_chunk_ids}
        hits = index.search_subset(query_vector, windows, top_k=k)
    else:
        hits = index.search(query_vector, top_k=k)

    results = []
    for parent, score, window in rollup(hits, top_k):
        chunk = chunks_by_id.get(parent)
        if chunk is not None:
            results.append({**chunk, "score": score, "matched_window": window})
    return results
