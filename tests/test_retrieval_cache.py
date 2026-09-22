from entitygraph_rag.retrieval import cache


def test_cache_roundtrip(tmp_path):
    key = cache.make_cache_key("doc::0::0", "some text", model_name="gemini-embedding-001", output_dimensionality=768)
    vector = [0.1, 0.2, 0.3]

    assert cache.read_cache(tmp_path, key) is None

    cache.write_cache(tmp_path, key, vector)

    assert cache.read_cache(tmp_path, key) == vector


def test_cache_key_changes_with_output_dimensionality():
    key_768 = cache.make_cache_key("doc::0::0", "text", model_name="gemini-embedding-001", output_dimensionality=768)
    key_1536 = cache.make_cache_key("doc::0::0", "text", model_name="gemini-embedding-001", output_dimensionality=1536)
    assert key_768 != key_1536
