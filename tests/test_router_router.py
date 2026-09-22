from types import SimpleNamespace

import entitygraph_rag.router.router as router_module
from entitygraph_rag.router.router import route_query


def _decision(route, **kwargs):
    return SimpleNamespace(route=route, entities=[], relation=None, graph_pattern=None, reasoning="because", **kwargs)


def test_route_query_dispatches_semantic(monkeypatch):
    monkeypatch.setattr(router_module, "classify_query", lambda *a, **k: _decision("semantic"))
    monkeypatch.setattr(router_module, "semantic_search", lambda *a, **k: [{"chunk_id": "c1"}])

    result = route_query(
        "what risks does NVIDIA face?", client=None, embedding_client=None, schema=None, store=None, index=None,
        chunks_by_id={}, entity_lookup=None,
    )

    assert result["route"] == "semantic"
    assert result["chunks"] == [{"chunk_id": "c1"}]
    assert result["query"] == "what risks does NVIDIA face?"
    assert result["classification_reasoning"] == "because"


def test_route_query_dispatches_relational(monkeypatch):
    monkeypatch.setattr(router_module, "classify_query", lambda *a, **k: _decision("relational"))
    monkeypatch.setattr(router_module, "run_relational", lambda *a, **k: {"route": "relational", "results": []})

    result = route_query(
        "who supplies NVIDIA?", client=None, embedding_client=None, schema=None, store=None, index=None,
        chunks_by_id={}, entity_lookup=None,
    )

    assert result["route"] == "relational"
    assert result["classification_reasoning"] == "because"


def test_route_query_dispatches_graph_guided_hybrid(monkeypatch):
    monkeypatch.setattr(router_module, "classify_query", lambda *a, **k: _decision("graph_guided_hybrid"))
    monkeypatch.setattr(
        router_module, "run_graph_guided_hybrid", lambda *a, **k: {"route": "graph_guided_hybrid", "chunks": []}
    )

    result = route_query(
        "what has NVIDIA said about TSMC?", client=None, embedding_client=None, schema=None, store=None, index=None,
        chunks_by_id={}, entity_lookup=None,
    )

    assert result["route"] == "graph_guided_hybrid"
