import numpy as np

from entitygraph_rag.retrieval.index import VectorIndex


def test_search_ranks_by_cosine_similarity():
    chunk_ids = ["a", "b", "c"]
    vectors = np.array(
        [
            [1.0, 0.0],  # a: identical direction to query
            [0.0, 1.0],  # b: orthogonal to query
            [-1.0, 0.0],  # c: opposite direction to query
        ]
    )
    index = VectorIndex(chunk_ids, vectors)

    results = index.search([1.0, 0.0], top_k=3)

    assert [chunk_id for chunk_id, _ in results] == ["a", "b", "c"]
    assert results[0][1] == 1.0
    assert results[2][1] == -1.0


def test_search_respects_top_k():
    chunk_ids = ["a", "b", "c"]
    vectors = np.eye(3)
    index = VectorIndex(chunk_ids, vectors)

    assert len(index.search([1.0, 0.0, 0.0], top_k=2)) == 2


def test_search_top_k_larger_than_corpus_returns_all():
    chunk_ids = ["a", "b"]
    vectors = np.eye(2)
    index = VectorIndex(chunk_ids, vectors)

    assert len(index.search([1.0, 0.0], top_k=100)) == 2


def test_vectors_are_normalized_regardless_of_input_magnitude():
    index = VectorIndex(["a"], np.array([[3.0, 4.0]]))  # magnitude 5
    assert np.allclose(np.linalg.norm(index.vectors[0]), 1.0)


def test_zero_vector_does_not_raise():
    index = VectorIndex(["a"], np.array([[0.0, 0.0]]))
    results = index.search([1.0, 0.0], top_k=1)
    assert results[0][0] == "a"


def test_search_subset_restricts_to_candidates():
    chunk_ids = ["a", "b", "c"]
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])  # all identical direction
    index = VectorIndex(chunk_ids, vectors)

    results = index.search_subset([1.0, 0.0], {"b", "c"}, top_k=5)

    assert {chunk_id for chunk_id, _ in results} == {"b", "c"}


def test_search_subset_empty_candidates_returns_empty():
    index = VectorIndex(["a", "b"], np.eye(2))
    assert index.search_subset([1.0, 0.0], set(), top_k=5) == []


def test_search_subset_candidates_not_in_index_are_ignored():
    index = VectorIndex(["a", "b"], np.eye(2))
    results = index.search_subset([1.0, 0.0], {"a", "nonexistent"}, top_k=5)
    assert [chunk_id for chunk_id, _ in results] == ["a"]


def test_save_and_load_roundtrip(tmp_path):
    chunk_ids = ["a", "b"]
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
    index = VectorIndex(chunk_ids, vectors)

    path = tmp_path / "index"
    index.save_to_file(path)
    reloaded = VectorIndex.from_file(path)

    assert reloaded.chunk_ids == chunk_ids
    assert np.allclose(reloaded.vectors, index.vectors)
