from reachfix.ingestion.schema import make_chunk_id


def test_chunk_id_determinism():
    first = make_chunk_id("ACC123", section_ordinal=2, chunk_index=0)
    second = make_chunk_id("ACC123", section_ordinal=2, chunk_index=0)

    assert first == second
    assert first == "ACC123::2::0"


def test_chunk_id_changes_with_chunk_index():
    a = make_chunk_id("ACC123", section_ordinal=2, chunk_index=0)
    b = make_chunk_id("ACC123", section_ordinal=2, chunk_index=1)

    assert a != b
