from types import SimpleNamespace

from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.graph import NetworkXGraphStore
from entitygraph_rag.retrieval.index import VectorIndex
from entitygraph_rag.router import EntityLookup
from entitygraph_rag.router.dispatch import common_neighbor_direction, run_graph_guided_hybrid, run_relational

TSMC = {"entity_id": "Company:tsmc", "canonical_name": "TSMC", "entity_type": "Company", "aliases": ["TSMC"]}
NVIDIA = {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA", "entity_type": "Company", "aliases": ["NVIDIA"]}
APPLE = {"entity_id": "Company:apple", "canonical_name": "Apple", "entity_type": "Company", "aliases": ["Apple"]}

SCHEMA = load_schema()


def _edge(subject_id, object_id, relation="SUPPLIES", chunk_id="c1"):
    return {
        "subject_id": subject_id, "object_id": object_id, "relation": relation,
        "confidence": 0.9, "source_chunk_id": chunk_id, "source_doc_id": "d1", "extracted_at": "t",
    }


def _decision(route, entities, relation=None, graph_pattern=None):
    return SimpleNamespace(route=route, entities=entities, relation=relation, graph_pattern=graph_pattern, reasoning="r")


def _store_with_supply_chain():
    # TSMC --SUPPLIES--> NVIDIA, TSMC --SUPPLIES--> Apple
    store = NetworkXGraphStore()
    for entity in (TSMC, NVIDIA, APPLE):
        store.upsert_entity(entity)
    store.upsert_edge(_edge("Company:tsmc", "Company:nvidia"))
    store.upsert_edge(_edge("Company:tsmc", "Company:apple"))
    return store


def test_run_relational_neighbors():
    store = _store_with_supply_chain()
    lookup = EntityLookup([TSMC, NVIDIA, APPLE])
    decision = _decision("relational", ["TSMC"], relation="SUPPLIES", graph_pattern="neighbors")

    result = run_relational(decision, schema=SCHEMA, store=store, entity_lookup=lookup)

    assert result["route"] == "relational"
    names = {r["canonical_name"] for r in result["results"]}
    assert names == {"NVIDIA", "Apple"}
    # each row carries its origin entity and edge provenance, for citations later
    assert all(r["source"]["canonical_name"] == "TSMC" for r in result["results"])
    assert all(len(r["provenance"]) == 1 for r in result["results"])


def test_run_relational_common_neighbors():
    store = _store_with_supply_chain()
    lookup = EntityLookup([TSMC, NVIDIA, APPLE])
    decision = _decision("relational", ["NVIDIA", "Apple"], relation="SUPPLIES", graph_pattern="common_neighbors")

    result = run_relational(decision, schema=SCHEMA, store=store, entity_lookup=lookup)

    assert [r["canonical_name"] for r in result["results"]] == ["TSMC"]
    assert {t["canonical_name"] for t in result["results"][0]["targets"]} == {"NVIDIA", "Apple"}


HF = {"entity_id": "Company:hf", "canonical_name": "Hugging Face", "entity_type": "Company", "aliases": ["Hugging Face"]}
RISK = {"entity_id": "RiskFactor:oss", "canonical_name": "Open-source restrictions", "entity_type": "RiskFactor", "aliases": []}
CHINA = {"entity_id": "Location:china", "canonical_name": "China", "entity_type": "Location", "aliases": ["China"]}


def _store_with_shared_objects():
    # NVIDIA and Hugging Face both DISCLOSED_RISK the same risk and both MENTION China.
    store = NetworkXGraphStore()
    store.load(
        [NVIDIA, HF, RISK, CHINA],
        [_edge("Company:nvidia", "RiskFactor:oss", "DISCLOSED_RISK"), _edge("Company:hf", "RiskFactor:oss", "DISCLOSED_RISK"),
         _edge("Company:nvidia", "Location:china", "MENTIONS"), _edge("Company:hf", "Location:china", "MENTIONS")],
    )
    return store


def test_run_relational_common_neighbors_shared_subjects():
    store = _store_with_shared_objects()
    lookup = EntityLookup([NVIDIA, HF, RISK, CHINA])
    decision = _decision("relational", ["NVIDIA", "Hugging Face"], relation="DISCLOSED_RISK", graph_pattern="common_neighbors")

    result = run_relational(decision, schema=SCHEMA, store=store, entity_lookup=lookup)

    assert [r["canonical_name"] for r in result["results"]] == ["Open-source restrictions"]
    assert result["results"][0]["direction"] == "out"


def test_run_relational_common_neighbors_without_relation_uses_both_directions():
    store = _store_with_shared_objects()
    lookup = EntityLookup([NVIDIA, HF, RISK, CHINA])
    decision = _decision("relational", ["NVIDIA", "Hugging Face"], graph_pattern="common_neighbors")

    result = run_relational(decision, schema=SCHEMA, store=store, entity_lookup=lookup)

    assert sorted(r["canonical_name"] for r in result["results"]) == ["China", "Open-source restrictions"]


def test_run_relational_common_neighbors_symmetric_relation():
    # COMPETES_WITH is stored one way only: AMD --> NVIDIA, Apple --> AMD.
    amd = {"entity_id": "Company:amd", "canonical_name": "AMD", "entity_type": "Company", "aliases": ["AMD"]}
    store = NetworkXGraphStore()
    store.load([NVIDIA, APPLE, amd], [_edge("Company:amd", "Company:nvidia", "COMPETES_WITH"),
                                      _edge("Company:apple", "Company:amd", "COMPETES_WITH")])
    lookup = EntityLookup([NVIDIA, APPLE, amd])
    decision = _decision("relational", ["NVIDIA", "Apple"], relation="COMPETES_WITH", graph_pattern="common_neighbors")

    result = run_relational(decision, schema=SCHEMA, store=store, entity_lookup=lookup)

    assert [r["canonical_name"] for r in result["results"]] == ["AMD"]


def test_common_neighbor_direction_from_schema():
    assert common_neighbor_direction(SCHEMA, "DISCLOSED_RISK", ["Company", "Company"]) == "out"
    assert common_neighbor_direction(SCHEMA, "EXECUTIVE_OF", ["Company", "Company"]) == "in"
    assert common_neighbor_direction(SCHEMA, "EXECUTIVE_OF", ["Person", "Person"]) == "out"
    assert common_neighbor_direction(SCHEMA, "SUPPLIES", ["Company", "Company"]) == "in"  # ambiguous → default
    assert common_neighbor_direction(SCHEMA, "COMPETES_WITH", ["Company", "Company"]) == "both"
    assert common_neighbor_direction(SCHEMA, None, ["Company", "Company"]) == "both"


def test_run_relational_unresolved_entity_returns_warning():
    store = _store_with_supply_chain()
    lookup = EntityLookup([TSMC, NVIDIA, APPLE])
    decision = _decision("relational", ["Some Unknown Company Xyz"], relation="SUPPLIES", graph_pattern="neighbors")

    result = run_relational(decision, schema=SCHEMA, store=store, entity_lookup=lookup)

    assert result["results"] == []
    assert "warning" in result


def test_run_graph_guided_hybrid_scopes_chunks_and_expands_entities(monkeypatch):
    store = _store_with_supply_chain()
    lookup = EntityLookup([TSMC, NVIDIA, APPLE])
    index = VectorIndex(["c1", "c2"], [[1.0, 0.0], [0.0, 1.0]])
    chunks_by_id = {
        "c1": {"chunk_id": "c1", "text": "TSMC supplies NVIDIA."},
        "c2": {"chunk_id": "c2", "text": "unrelated chunk"},
    }
    decision = _decision("graph_guided_hybrid", ["TSMC"])

    import entitygraph_rag.router.dispatch as dispatch_module
    monkeypatch.setattr(dispatch_module, "semantic_search", lambda *a, **k: [chunks_by_id[cid] for cid in k["candidate_chunk_ids"]])

    result = run_graph_guided_hybrid(
        "what does TSMC supply?", decision, store=store, entity_lookup=lookup,
        index=index, chunks_by_id=chunks_by_id, embedding_client=None,
    )

    assert result["route"] == "graph_guided_hybrid"
    expanded_names = {e["canonical_name"] for e in result["expanded_entities"]}
    assert expanded_names == {"TSMC", "NVIDIA", "Apple"}
    assert result["chunks"] == [chunks_by_id["c1"]]  # only the edge's source chunk, not c2

    edge_names = {e["canonical_name"] for e in result["edges"]}
    assert edge_names == {"NVIDIA", "Apple"}
    assert all(e["source"]["canonical_name"] == "TSMC" for e in result["edges"])
