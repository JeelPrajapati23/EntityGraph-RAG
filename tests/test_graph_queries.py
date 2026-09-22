from entitygraph_rag.graph import NetworkXGraphStore, common_neighbors, two_hop_neighbors


def _edge(subject_id, object_id, relation="SUPPLIES"):
    return {
        "subject_id": subject_id, "object_id": object_id, "relation": relation,
        "confidence": 0.9, "source_chunk_id": "c", "source_doc_id": "d", "extracted_at": "t",
    }


def test_two_hop_neighbors_follows_chain():
    # A --SUPPLIES--> B --SUPPLIES--> C
    store = NetworkXGraphStore()
    store.upsert_edge(_edge("A", "B"))
    store.upsert_edge(_edge("B", "C"))

    result = two_hop_neighbors(store, "A", relation="SUPPLIES")

    assert result == [{"via": "B", "target": "C", "relation": "SUPPLIES"}]


def test_two_hop_neighbors_skips_cycle_back_to_start():
    # A --SUPPLIES--> B --SUPPLIES--> A (cycle)
    store = NetworkXGraphStore()
    store.upsert_edge(_edge("A", "B"))
    store.upsert_edge(_edge("B", "A"))

    assert two_hop_neighbors(store, "A", relation="SUPPLIES") == []


def test_two_hop_neighbors_respects_relation_filter():
    store = NetworkXGraphStore()
    store.upsert_edge(_edge("A", "B", relation="SUPPLIES"))
    store.upsert_edge(_edge("B", "C", relation="COMPETES_WITH"))

    assert two_hop_neighbors(store, "A", relation="SUPPLIES") == []


def test_common_neighbors_finds_shared_supplier():
    # X --SUPPLIES--> A, X --SUPPLIES--> B, Y --SUPPLIES--> A only
    store = NetworkXGraphStore()
    store.upsert_edge(_edge("X", "A"))
    store.upsert_edge(_edge("X", "B"))
    store.upsert_edge(_edge("Y", "A"))

    assert common_neighbors(store, "A", "B", relation="SUPPLIES", direction="in") == ["X"]


def test_common_neighbors_empty_when_no_overlap():
    store = NetworkXGraphStore()
    store.upsert_edge(_edge("X", "A"))
    store.upsert_edge(_edge("Y", "B"))

    assert common_neighbors(store, "A", "B", relation="SUPPLIES", direction="in") == []
