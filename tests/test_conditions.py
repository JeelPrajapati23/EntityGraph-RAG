import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from entitygraph_rag.conditions import pipeline as pipeline_module
from entitygraph_rag.conditions.model import build_extraction_model
from entitygraph_rag.conditions.pipeline import evidence_match, extract_conditions
from entitygraph_rag.conditions.prompt import build_system_prompt, build_user_prompt
from entitygraph_rag.extraction.schema import load_schema

SCHEMA_V2 = Path(__file__).resolve().parent.parent / "schema" / "v2.yaml"
CATEGORIES = {"input_source", "configuration", "api_usage", "platform", "other"}

CHUNK = {
    "chunk_id": "GHSA-74fj-2j2h-c42q::0",
    "doc_id": "GHSA-74fj-2j2h-c42q",
    "source_url": "https://osv.dev/vulnerability/GHSA-74fj-2j2h-c42q",
    "summary": "Exposure of headers in follow-redirects",
    "affected_packages": ["follow-redirects"],
    "text": "### Impact\n\nWhen `maxRedirects` is raised above the default and the client follows "
            "redirects to [other hosts][], the `Cookie` header is sent to the new host.",
}


@pytest.fixture(scope="module")
def schema():
    return load_schema(SCHEMA_V2)


@pytest.fixture(scope="module")
def model(schema):
    return build_extraction_model(schema)


def item(**overrides):
    base = {"relation": "EXPLOITABLE_WHEN", "text": "`maxRedirects` is raised above the default",
            "category": "configuration", "evidence": "When `maxRedirects` is raised above the default",
            "confidence": 0.9}
    return {**base, **overrides}


def test_v2_loader_reads_extraction_and_property_values(schema):
    assert set(schema.llm_edge_types()) == {"EXPLOITABLE_WHEN"}
    assert schema.edge_types["DEPENDS_ON"].extraction == "deterministic"
    assert set(schema.node_types["ExploitCondition"].property_values["category"]) == CATEGORIES


def test_v1_edges_default_to_llm():
    v1 = load_schema()
    assert set(v1.llm_edge_types()) == set(v1.edge_types)


def test_model_is_generated_from_llm_edges_only(model):
    fields = model.model_fields
    assert set(get_args(fields["relation"].annotation)) == {"EXPLOITABLE_WHEN"}
    assert set(get_args(fields["category"].annotation)) == CATEGORIES
    assert set(fields) == {"relation", "text", "category", "evidence", "confidence"}


def test_model_rejects_off_vocabulary_values(model):
    with pytest.raises(ValidationError):
        model(**item(category="network"))
    with pytest.raises(ValidationError):
        model(**item(relation="DEPENDS_ON"))
    with pytest.raises(ValidationError):
        model(**item(confidence=1.5))


def test_prompt_lists_llm_edges_and_categories_but_not_deterministic_edges(schema):
    prompt = build_system_prompt(schema)
    assert "EXPLOITABLE_WHEN" in prompt
    assert all(c in prompt for c in CATEGORIES)
    assert "DEPENDS_ON" not in prompt and "HAS_VULNERABILITY" not in prompt


def test_user_prompt_carries_advisory_context():
    prompt = build_user_prompt(CHUNK)
    assert "GHSA-74fj-2j2h-c42q" in prompt and "follow-redirects" in prompt and CHUNK["text"] in prompt


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ("When `maxRedirects` is raised above the default", "exact"),
        ("when maxRedirects is   RAISED above the default", "exact"),        # case, whitespace, backticks
        ("follows redirects to other hosts", "exact"),                       # markdown link brackets
        ("the client follows redirects to other hosts the Cookie header", "fuzzy"),  # dropped comma + "the"
        ("the Cookie header is stripped", None),
        ("other hosts", "exact"),
        ("other hostz", None),                                               # short quotes must be exact
        ("Exposure of headers", "exact"),                                    # found in the summary
        ("", None),
    ],
)
def test_evidence_match(evidence, expected):
    assert evidence_match(evidence, CHUNK) == expected


def run(monkeypatch, tmp_path, schema, model, raw):
    calls = []

    def fake_generate_json(*args, **kwargs):
        calls.append(kwargs)
        return raw

    monkeypatch.setattr(pipeline_module, "generate_json", fake_generate_json)
    edges, warnings = extract_conditions(
        CHUNK, schema=schema, model=model, client=None, model_name="m", system_prompt="sys", cache_root=tmp_path,
    )
    return edges, warnings, calls


def test_extract_conditions_builds_provenance_and_drops_unsupported(monkeypatch, tmp_path, schema, model):
    raw = json.dumps({"extractions": [item(), item(text="made up", evidence="never said this at all")]})

    edges, warnings, _ = run(monkeypatch, tmp_path, schema, model, raw)

    [edge] = edges
    assert edge["subject"] == "GHSA-74fj-2j2h-c42q"
    assert edge["relation"] == "EXPLOITABLE_WHEN" and edge["extraction_method"] == "llm"
    assert edge["source_chunk_id"] == CHUNK["chunk_id"] and edge["source_url"] == CHUNK["source_url"]
    assert edge["condition_id"] == "GHSA-74fj-2j2h-c42q::0::0"
    assert edge["evidence_match"] == "exact"
    assert len(warnings) == 1 and "made up" in warnings[0]


def test_results_are_cached_and_parse_failures_are_not(monkeypatch, tmp_path, schema, model):
    run(monkeypatch, tmp_path, schema, model, json.dumps({"extractions": [item()]}))
    edges, _, calls = run(monkeypatch, tmp_path, schema, model, "should not be called")
    assert calls == [] and len(edges) == 1

    other_cache = tmp_path / "other"
    monkeypatch.setattr(pipeline_module, "generate_json", lambda *a, **k: '{"extractions": [{"relation": "X"}]}')
    edges, warnings = extract_conditions(
        CHUNK, schema=schema, model=model, client=None, model_name="m", system_prompt="sys", cache_root=other_cache,
    )
    assert edges == [] and "failed to parse" in warnings[0]
    assert not other_cache.exists()
