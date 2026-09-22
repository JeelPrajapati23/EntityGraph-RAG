import json

import pytest

from entitygraph_rag.extraction import pipeline as pipeline_module
from entitygraph_rag.extraction.pipeline import extract_for_chunk
from entitygraph_rag.extraction.schema import build_triple_model, load_schema

CHUNK = {"chunk_id": "ACC1::0::0", "doc_id": "ACC1", "text": "TSMC fabricates chips for NVIDIA."}


@pytest.fixture(scope="module")
def schema():
    return load_schema()


@pytest.fixture(scope="module")
def triple_model(schema):
    return build_triple_model(schema)


def _patch_call_gemini(monkeypatch, raw_json: str):
    monkeypatch.setattr(pipeline_module, "call_gemini", lambda *args, **kwargs: raw_json)


def test_extract_for_chunk_accepts_valid_triple(monkeypatch, tmp_path, schema, triple_model):
    raw = json.dumps(
        [
            {
                "subject": "TSMC", "subject_type": "Company", "relation": "SUPPLIES",
                "object": "NVIDIA", "object_type": "Company", "confidence": 0.95,
            }
        ]
    )
    _patch_call_gemini(monkeypatch, raw)

    edges, warnings = extract_for_chunk(
        CHUNK, schema=schema, triple_model=triple_model, client=None, model_name="gemini-2.5-flash",
        system_prompt="prompt", cache_root=tmp_path,
    )

    assert warnings == []
    assert len(edges) == 1
    edge = edges[0]
    assert edge["subject"] == "TSMC"
    assert edge["relation"] == "SUPPLIES"
    assert edge["source_chunk_id"] == "ACC1::0::0"
    assert edge["source_doc_id"] == "ACC1"
    assert "extracted_at" in edge


def test_extract_for_chunk_drops_schema_invalid_triple(monkeypatch, tmp_path, schema, triple_model):
    raw = json.dumps(
        [
            {
                "subject": "NVIDIA", "subject_type": "Company", "relation": "AUDITED_BY",
                "object": "Jensen Huang", "object_type": "Person", "confidence": 0.7,
            }
        ]
    )
    _patch_call_gemini(monkeypatch, raw)

    edges, warnings = extract_for_chunk(
        {**CHUNK, "chunk_id": "ACC2::0::0"}, schema=schema, triple_model=triple_model, client=None,
        model_name="gemini-2.5-flash", system_prompt="prompt", cache_root=tmp_path,
    )

    assert edges == []
    assert len(warnings) == 1
    assert "AUDITED_BY" in warnings[0]


def test_extract_for_chunk_handles_malformed_llm_output(monkeypatch, tmp_path, schema, triple_model):
    _patch_call_gemini(monkeypatch, "not json at all")

    edges, warnings = extract_for_chunk(
        {**CHUNK, "chunk_id": "ACC3::0::0"}, schema=schema, triple_model=triple_model, client=None,
        model_name="gemini-2.5-flash", system_prompt="prompt", cache_root=tmp_path,
    )

    assert edges == []
    assert len(warnings) == 1
    assert "ACC3::0::0" in warnings[0]


def test_extract_for_chunk_uses_cache_on_second_call(monkeypatch, tmp_path, schema, triple_model):
    raw = json.dumps(
        [
            {
                "subject": "TSMC", "subject_type": "Company", "relation": "SUPPLIES",
                "object": "NVIDIA", "object_type": "Company", "confidence": 0.95,
            }
        ]
    )
    calls = {"n": 0}

    def fake_call_gemini(*args, **kwargs):
        calls["n"] += 1
        return raw

    monkeypatch.setattr(pipeline_module, "call_gemini", fake_call_gemini)

    chunk = {**CHUNK, "chunk_id": "ACC4::0::0"}
    first_edges, _ = extract_for_chunk(
        chunk, schema=schema, triple_model=triple_model, client=None, model_name="gemini-2.5-flash",
        system_prompt="prompt", cache_root=tmp_path,
    )
    second_edges, second_warnings = extract_for_chunk(
        chunk, schema=schema, triple_model=triple_model, client=None, model_name="gemini-2.5-flash",
        system_prompt="prompt", cache_root=tmp_path,
    )

    assert calls["n"] == 1  # second call served from cache, no re-call
    assert second_edges == first_edges
    assert second_warnings == []
