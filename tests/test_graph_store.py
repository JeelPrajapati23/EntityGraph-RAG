from entitygraph_rag.graph import NetworkXGraphStore

TSMC = {"entity_id": "Company:tsmc", "canonical_name": "TSMC", "entity_type": "Company", "aliases": ["TSMC"]}
NVIDIA = {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA", "entity_type": "Company", "aliases": ["NVIDIA"]}

EDGE_1 = {
    "subject_id": "Company:tsmc", "object_id": "Company:nvidia", "relation": "SUPPLIES",
    "confidence": 0.8, "source_chunk_id": "c1", "source_doc_id": "d1", "extracted_at": "t1",
}
EDGE_2 = {
    "subject_id": "Company:tsmc", "object_id": "Company:nvidia", "relation": "SUPPLIES",
    "confidence": 0.95, "source_chunk_id": "c2", "source_doc_id": "d2", "extracted_at": "t2",
}
EDGE_COMPETES = {
    "subject_id": "Company:tsmc", "object_id": "Company:nvidia", "relation": "COMPETES_WITH",
    "confidence": 0.5, "source_chunk_id": "c3", "source_doc_id": "d1", "extracted_at": "t3",
}


def _store_with_nodes():
    store = NetworkXGraphStore()
    store.upsert_entity(TSMC)
    store.upsert_entity(NVIDIA)
    return store


def test_upsert_entity_then_get():
    store = _store_with_nodes()
    assert store.get_entity("Company:tsmc") == TSMC


def test_get_entity_missing_returns_none():
    store = NetworkXGraphStore()
    assert store.get_entity("Company:nope") is None


def test_upsert_edge_creates_edge_with_single_provenance():
    store = _store_with_nodes()
    store.upsert_edge(EDGE_1)

    neighbors = store.neighbors("Company:tsmc", direction="out")
    assert len(neighbors) == 1
    assert neighbors[0]["entity_id"] == "Company:nvidia"
    assert neighbors[0]["relation"] == "SUPPLIES"
    assert len(neighbors[0]["provenance"]) == 1


def test_repeated_edge_merges_provenance_instead_of_duplicating():
    store = _store_with_nodes()
    store.upsert_edge(EDGE_1)
    store.upsert_edge(EDGE_2)

    assert store.edge_count() == 1
    neighbors = store.neighbors("Company:tsmc", relation="SUPPLIES", direction="out")
    assert len(neighbors) == 1
    assert len(neighbors[0]["provenance"]) == 2
    assert neighbors[0]["confidence"] == 0.95  # max of 0.8, 0.95


def test_different_relation_between_same_pair_is_a_separate_edge():
    store = _store_with_nodes()
    store.upsert_edge(EDGE_1)
    store.upsert_edge(EDGE_COMPETES)

    assert store.edge_count() == 2
    relations = {n["relation"] for n in store.neighbors("Company:tsmc", direction="out")}
    assert relations == {"SUPPLIES", "COMPETES_WITH"}


def test_neighbors_direction_filtering():
    store = _store_with_nodes()
    store.upsert_edge(EDGE_1)

    assert len(store.neighbors("Company:tsmc", direction="out")) == 1
    assert len(store.neighbors("Company:tsmc", direction="in")) == 0
    assert len(store.neighbors("Company:nvidia", direction="in")) == 1
    assert len(store.neighbors("Company:nvidia", direction="out")) == 0
    assert len(store.neighbors("Company:tsmc", direction="both")) == 1


def test_node_and_edge_counts():
    store = _store_with_nodes()
    store.upsert_edge(EDGE_1)
    assert store.node_count() == 2
    assert store.edge_count() == 1


def test_load_bulk_loads_entities_and_edges():
    store = NetworkXGraphStore()
    store.load([TSMC, NVIDIA], [EDGE_1])
    assert store.node_count() == 2
    assert store.edge_count() == 1


def test_save_and_load_roundtrip(tmp_path):
    store = _store_with_nodes()
    store.upsert_edge(EDGE_1)

    path = tmp_path / "graph.pkl"
    store.save_to_file(path)
    reloaded = NetworkXGraphStore.from_file(path)

    assert reloaded.node_count() == store.node_count()
    assert reloaded.edge_count() == store.edge_count()
    assert reloaded.get_entity("Company:tsmc") == TSMC
