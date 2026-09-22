"""Synthetic fixtures only — no real artifacts, no Groq/HF calls."""
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import entitygraph_rag.api.app as app_module
from entitygraph_rag.api import Resources, create_app
from entitygraph_rag.api.views import result_subgraph
from entitygraph_rag.graph import NetworkXGraphStore
from entitygraph_rag.router import EntityLookup

ENTITIES = [
    {"entity_id": "Company:tsmc", "canonical_name": "TSMC", "entity_type": "Company", "aliases": ["TSMC"]},
    {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA", "entity_type": "Company", "aliases": ["NVIDIA"]},
]
EDGE = {
    "subject_id": "Company:tsmc", "object_id": "Company:nvidia", "relation": "SUPPLIES",
    "confidence": 0.9, "source_chunk_id": "c1", "source_doc_id": "d1", "extracted_at": "t",
}
TSMC = {"entity_id": "Company:tsmc", "canonical_name": "TSMC"}
NVIDIA = {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA"}
RELATIONAL_RESULT = {
    "route": "relational", "pattern": "neighbors", "query": "who supplies NVIDIA?",
    "classification_reasoning": "asks for a relation",
    "results": [{**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "in", "confidence": 0.9,
                 "provenance": [{"source_chunk_id": "c1"}]}],
}


@pytest.fixture
def store():
    store = NetworkXGraphStore()
    store.load(ENTITIES, [EDGE])
    return store


@pytest.fixture
def client(store):
    resources = Resources(
        chunks_by_id={"c1": {"chunk_id": "c1"}}, entity_lookup=EntityLookup(ENTITIES), store=store,
        index=None, schema=None, client=None, embedding_client=None,
    )
    with TestClient(create_app(resources)) as test_client:
        yield test_client


def test_health_reports_sizes(client):
    assert client.get("/health").json() == {"status": "ok", "nodes": 2, "edges": 1, "chunks": 1}


def test_index_serves_demo_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "EntityGraph-RAG" in resp.text


def test_explore_resolves_alias_and_returns_subgraph(client):
    body = client.get("/graph/explore", params={"entity": "nvidia"}).json()

    assert body["entity_id"] == "Company:nvidia"
    assert {n["entity_id"] for n in body["nodes"]} == {"Company:nvidia", "Company:tsmc"}
    assert body["edges"] == [{"source": "Company:tsmc", "target": "Company:nvidia", "relation": "SUPPLIES",
                              "confidence": 0.9, "n_citations": 1}]


def test_explore_unknown_entity_is_404(client):
    assert client.get("/graph/explore", params={"entity": "Zzyzx Holdings"}).status_code == 404


def test_query_returns_answer_citations_and_subgraph(client, monkeypatch):
    monkeypatch.setattr(app_module, "route_query", lambda *a, **k: dict(RELATIONAL_RESULT))
    monkeypatch.setattr(app_module, "synthesize_answer", lambda result, **k: {
        "query": result["query"], "route": result["route"], "answer": "TSMC supplies NVIDIA.",
        "citations": {"chunks": [], "graph_paths": ["TSMC --SUPPLIES--> NVIDIA"]},
    })

    body = client.post("/query", json={"query": "who supplies NVIDIA?"}).json()

    assert body["answer"] == "TSMC supplies NVIDIA."
    assert body["route"] == "relational"
    assert body["classification_reasoning"] == "asks for a relation"
    assert body["subgraph"]["edges"] == [{"source": "Company:tsmc", "target": "Company:nvidia", "relation": "SUPPLIES"}]


def test_query_rejects_empty_query(client):
    assert client.post("/query", json={"query": ""}).status_code == 422


def test_query_maps_malformed_classification_to_502(client, monkeypatch):
    class Decision(BaseModel):
        route: int

    def bad_route(*a, **k):
        Decision.model_validate({"route": "not-an-int"})

    monkeypatch.setattr(app_module, "route_query", bad_route)

    resp = client.post("/query", json={"query": "who supplies NVIDIA?"})
    assert resp.status_code == 502
    assert "router classification failed" in resp.json()["detail"]


def test_result_subgraph_two_hop(store):
    result = {"route": "relational", "pattern": "two_hop", "results": [{
        "source": {"entity_id": "Company:tsmc"}, "via": {"entity_id": "Company:nvidia"},
        "target": {"entity_id": "Company:x"}, "first_relation": "SUPPLIES", "relation": "SUPPLIES",
    }]}

    sub = result_subgraph(result, store)

    assert [(e["source"], e["target"]) for e in sub["edges"]] == [
        ("Company:tsmc", "Company:nvidia"), ("Company:nvidia", "Company:x"),
    ]
    unknown = next(n for n in sub["nodes"] if n["entity_id"] == "Company:x")
    assert unknown["canonical_name"] == "Company:x"


def test_result_subgraph_dedupes_hybrid_edges_seen_from_both_ends(store):
    result = {"route": "graph_guided_hybrid", "edges": [
        {**NVIDIA, "source": TSMC, "relation": "SUPPLIES", "direction": "out"},
        {**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "in"},
    ]}
    assert len(result_subgraph(result, store)["edges"]) == 1


def test_result_subgraph_semantic_is_empty(store):
    assert result_subgraph({"route": "semantic", "chunks": []}, store) == {"nodes": [], "edges": []}
