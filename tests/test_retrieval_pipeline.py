from entitygraph_rag.retrieval import pipeline as pipeline_module
from entitygraph_rag.retrieval.pipeline import embed_chunks

CHUNKS = [
    {"chunk_id": "d::0::0", "text": "TSMC fabricates chips for NVIDIA."},
    {"chunk_id": "d::0::1", "text": "NVIDIA competes with AMD and Intel."},
    {"chunk_id": "d::0::2", "text": "Jensen Huang is CEO of NVIDIA."},
]


def _fake_embed_texts(client, texts, *, task_type, model_name, output_dimensionality):
    # deterministic per-text vector so assertions can check chunk<->vector mapping
    return [[float(len(t)), 0.0] for t in texts]


def test_embed_chunks_embeds_every_chunk(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_module, "embed_texts", _fake_embed_texts)

    chunk_ids, vectors = embed_chunks(
        CHUNKS, client=None, model_name="m", output_dimensionality=2, cache_root=tmp_path
    )

    assert chunk_ids == [c["chunk_id"] for c in CHUNKS]
    assert vectors.shape == (3, 2)
    assert vectors[0][0] == float(len(CHUNKS[0]["text"]))


def test_embed_chunks_uses_cache_on_second_call(monkeypatch, tmp_path):
    calls = {"n": 0}

    def counting_embed_texts(client, texts, **kwargs):
        calls["n"] += 1
        return _fake_embed_texts(client, texts, **kwargs)

    monkeypatch.setattr(pipeline_module, "embed_texts", counting_embed_texts)

    embed_chunks(CHUNKS, client=None, model_name="m", output_dimensionality=2, cache_root=tmp_path)
    embed_chunks(CHUNKS, client=None, model_name="m", output_dimensionality=2, cache_root=tmp_path)

    assert calls["n"] == 1  # second call fully served from cache


def test_embed_chunks_batches_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_module, "EMBED_BATCH_SIZE", 2)
    call_sizes = []

    def recording_embed_texts(client, texts, **kwargs):
        call_sizes.append(len(texts))
        return _fake_embed_texts(client, texts, **kwargs)

    monkeypatch.setattr(pipeline_module, "embed_texts", recording_embed_texts)

    embed_chunks(CHUNKS, client=None, model_name="m", output_dimensionality=2, cache_root=tmp_path)

    assert call_sizes == [2, 1]  # 3 chunks, batch size 2 -> two calls
