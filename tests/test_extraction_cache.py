from reachfix.extraction import cache


def test_cache_roundtrip(tmp_path):
    key = cache.make_cache_key("GHSA-hrpp-h998-j3pp::0", "some text", model_name="openai/gpt-oss-120b", schema_version=1)
    edges = [{"subject": "GHSA-hrpp-h998-j3pp", "relation": "EXPLOITABLE_WHEN", "object": "query strings are parsed"}]

    assert cache.read_cache(tmp_path, key) is None

    cache.write_cache(tmp_path, key, edges)

    assert cache.read_cache(tmp_path, key) == edges


def test_cache_key_changes_with_chunk_text():
    key_a = cache.make_cache_key("GHSA-hrpp-h998-j3pp::0", "text A", model_name="openai/gpt-oss-120b", schema_version=1)
    key_b = cache.make_cache_key("GHSA-hrpp-h998-j3pp::0", "text B", model_name="openai/gpt-oss-120b", schema_version=1)
    assert key_a != key_b


def test_cache_key_changes_with_schema_version():
    key_v1 = cache.make_cache_key("GHSA-hrpp-h998-j3pp::0", "text", model_name="openai/gpt-oss-120b", schema_version=1)
    key_v2 = cache.make_cache_key("GHSA-hrpp-h998-j3pp::0", "text", model_name="openai/gpt-oss-120b", schema_version=2)
    assert key_v1 != key_v2
