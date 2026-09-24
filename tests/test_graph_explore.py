from reachfix.graph import NetworkXGraphStore, ego_subgraph


def _entity(entity_id, name):
    return {"entity_id": entity_id, "canonical_name": name, "entity_type": "PackageVersion", "aliases": [name]}


def _edge(subject_id, relation, object_id, chunk_id="c1"):
    return {
        "subject_id": subject_id, "object_id": object_id, "relation": relation,
        "confidence": 0.9, "source_chunk_id": chunk_id, "source_doc_id": "d1", "extracted_at": "t",
    }


def _chain_store():
    # express --DEPENDS_ON--> body-parser --DEPENDS_ON--> qs --HAS_VULNERABILITY--> ghsa
    store = NetworkXGraphStore()
    store.load(
        [_entity("express", "express@4.17.1"), _entity("body-parser", "body-parser@1.19.0"),
         _entity("qs", "qs@6.7.0"), _entity("ghsa", "GHSA-hrpp-h998-j3pp")],
        [_edge("express", "DEPENDS_ON", "body-parser"), _edge("body-parser", "DEPENDS_ON", "qs"),
         _edge("qs", "HAS_VULNERABILITY", "ghsa")],
    )
    return store


def test_depth_one_covers_both_directions():
    sub = ego_subgraph(_chain_store(), "qs", depth=1)

    assert {n["entity_id"] for n in sub["nodes"]} == {"qs", "body-parser", "ghsa"}
    assert {(e["source"], e["relation"], e["target"]) for e in sub["edges"]} == {
        ("body-parser", "DEPENDS_ON", "qs"), ("qs", "HAS_VULNERABILITY", "ghsa"),
    }


def test_depth_two_reaches_second_hop_without_duplicate_edges():
    sub = ego_subgraph(_chain_store(), "qs", depth=2)

    assert {n["entity_id"] for n in sub["nodes"]} == {"express", "body-parser", "qs", "ghsa"}
    assert len(sub["edges"]) == 3


def test_nodes_carry_display_fields():
    sub = ego_subgraph(_chain_store(), "ghsa", depth=1)
    ghsa = next(n for n in sub["nodes"] if n["entity_id"] == "ghsa")
    assert ghsa == {"entity_id": "ghsa", "canonical_name": "GHSA-hrpp-h998-j3pp", "entity_type": "PackageVersion"}


def test_max_nodes_caps_expansion():
    sub = ego_subgraph(_chain_store(), "qs", depth=2, max_nodes=2)
    assert len(sub["nodes"]) == 2
    node_ids = {n["entity_id"] for n in sub["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in sub["edges"])


def test_unknown_entity_returns_empty():
    assert ego_subgraph(_chain_store(), "nope") == {"nodes": [], "edges": []}
