import numpy as np

from entitygraph_rag.retrieval import search as search_module
from entitygraph_rag.retrieval.index import VectorIndex
from entitygraph_rag.retrieval.search import semantic_search

CHUNKS_BY_ID = {
    "a": {"chunk_id": "a", "text": "TSMC fabricates chips for NVIDIA."},
    "b": {"chunk_id": "b", "text": "Jensen Huang is CEO of NVIDIA."},
}
INDEX = VectorIndex(["a", "b"], np.array([[1.0, 0.0], [0.0, 1.0]]))


def test_semantic_search_returns_chunks_with_scores(monkeypatch):
    monkeypatch.setattr(search_module, "embed_texts", lambda *a, **k: [[1.0, 0.0]])

    results = semantic_search("who supplies NVIDIA?", index=INDEX, chunks_by_id=CHUNKS_BY_ID, client=None, top_k=2)

    assert len(results) == 2
    assert results[0]["chunk_id"] == "a"
    assert results[0]["score"] == 1.0
    assert "text" in results[0]


def test_semantic_search_skips_chunk_ids_missing_from_lookup(monkeypatch):
    monkeypatch.setattr(search_module, "embed_texts", lambda *a, **k: [[1.0, 0.0]])
    partial_lookup = {"a": CHUNKS_BY_ID["a"]}  # "b" deliberately missing

    results = semantic_search("query", index=INDEX, chunks_by_id=partial_lookup, client=None, top_k=2)

    assert [r["chunk_id"] for r in results] == ["a"]
