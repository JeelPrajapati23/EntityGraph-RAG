from entitygraph_rag.ingestion.chunker import pack_units


def _words(n: int, prefix: str) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_pack_units_respects_max_words_no_split():
    small_paragraphs = [_words(50, "a") for _ in range(4)]
    oversized_paragraph = _words(600, "b")
    units = small_paragraphs[:2] + [oversized_paragraph] + small_paragraphs[2:]

    chunks = pack_units(units, max_words=450)

    oversized_chunks = [c for c in chunks if oversized_paragraph in c]
    assert len(oversized_chunks) == 1
    assert oversized_chunks[0] == oversized_paragraph  # whole, unsplit, alone in its chunk

    for chunk in chunks:
        if chunk != oversized_paragraph:
            assert len(chunk.split()) <= 450
