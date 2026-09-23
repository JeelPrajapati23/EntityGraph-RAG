from reachfix.graph import NetworkXGraphStore, ego_subgraph


def _entity(entity_id, name):
    return {"entity_id": entity_id, "canonical_name": name, "entity_type": "Company", "aliases": [name]}


def _edge(subject_id, relation, object_id, chunk_id="c1"):
    return {
        "subject_id": subject_id, "object_id": object_id, "relation": relation,
        "confidence": 0.9, "source_chunk_id": chunk_id, "source_doc_id": "d1", "extracted_at": "t",
    }


def _chain_store():
    # asml --SUPPLIES--> tsmc --SUPPLIES--> nvidia --COMPETES_WITH--> amd
    store = NetworkXGraphStore()
    store.load(
        [_entity("asml", "ASML"), _entity("tsmc", "TSMC"), _entity("nvidia", "NVIDIA"), _entity("amd", "AMD")],
        [_edge("asml", "SUPPLIES", "tsmc"), _edge("tsmc", "SUPPLIES", "nvidia"),
         _edge("nvidia", "COMPETES_WITH", "amd")],
    )
    return store


def test_depth_one_covers_both_directions():
    sub = ego_subgraph(_chain_store(), "nvidia", depth=1)

    assert {n["entity_id"] for n in sub["nodes"]} == {"nvidia", "tsmc", "amd"}
    assert {(e["source"], e["relation"], e["target"]) for e in sub["edges"]} == {
        ("tsmc", "SUPPLIES", "nvidia"), ("nvidia", "COMPETES_WITH", "amd"),
    }


def test_depth_two_reaches_second_hop_without_duplicate_edges():
    sub = ego_subgraph(_chain_store(), "nvidia", depth=2)

    assert {n["entity_id"] for n in sub["nodes"]} == {"asml", "tsmc", "nvidia", "amd"}
    assert len(sub["edges"]) == 3


def test_nodes_carry_display_fields():
    sub = ego_subgraph(_chain_store(), "amd", depth=1)
    amd = next(n for n in sub["nodes"] if n["entity_id"] == "amd")
    assert amd == {"entity_id": "amd", "canonical_name": "AMD", "entity_type": "Company"}


def test_max_nodes_caps_expansion():
    sub = ego_subgraph(_chain_store(), "nvidia", depth=2, max_nodes=2)
    assert len(sub["nodes"]) == 2
    node_ids = {n["entity_id"] for n in sub["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in sub["edges"])


def test_unknown_entity_returns_empty():
    assert ego_subgraph(_chain_store(), "nope") == {"nodes": [], "edges": []}
