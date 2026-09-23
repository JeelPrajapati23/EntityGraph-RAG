from reachfix.extraction import cache


def test_cache_roundtrip(tmp_path):
    key = cache.make_cache_key("doc::0::0", "some text", model_name="gemini-2.5-flash", schema_version=1)
    edges = [{"subject": "NVIDIA", "relation": "SUPPLIES", "object": "TSMC"}]

    assert cache.read_cache(tmp_path, key) is None

    cache.write_cache(tmp_path, key, edges)

    assert cache.read_cache(tmp_path, key) == edges


def test_cache_key_changes_with_chunk_text():
    key_a = cache.make_cache_key("doc::0::0", "text A", model_name="gemini-2.5-flash", schema_version=1)
    key_b = cache.make_cache_key("doc::0::0", "text B", model_name="gemini-2.5-flash", schema_version=1)
    assert key_a != key_b


def test_cache_key_changes_with_schema_version():
    key_v1 = cache.make_cache_key("doc::0::0", "text", model_name="gemini-2.5-flash", schema_version=1)
    key_v2 = cache.make_cache_key("doc::0::0", "text", model_name="gemini-2.5-flash", schema_version=2)
    assert key_v1 != key_v2
