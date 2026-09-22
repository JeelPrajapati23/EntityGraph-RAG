from entitygraph_rag.synthesis.citations import (
    chunk_citation,
    format_common_neighbor_paths,
    format_edge_path,
    format_two_hop_path,
    graph_paths_for_result,
    graph_provenance_chunk_ids,
)

NVIDIA = {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA"}
TSMC = {"entity_id": "Company:tsmc", "canonical_name": "TSMC"}
APPLE = {"entity_id": "Company:apple", "canonical_name": "Apple"}


def test_format_edge_path_outgoing():
    row = {**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "out"}
    assert format_edge_path(row) == "NVIDIA --SUPPLIES--> TSMC"


def test_format_edge_path_incoming():
    row = {**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "in"}
    assert format_edge_path(row) == "TSMC --SUPPLIES--> NVIDIA"


def test_format_edge_path_none_relation_falls_back_to_mentions():
    row = {**TSMC, "source": NVIDIA, "relation": None, "direction": "out"}
    assert format_edge_path(row) == "NVIDIA --MENTIONS--> TSMC"


def test_format_two_hop_path():
    row = {"source": NVIDIA, "via": TSMC, "target": APPLE, "first_relation": "SUPPLIES", "relation": "SUPPLIES"}
    assert format_two_hop_path(row) == "NVIDIA --SUPPLIES--> TSMC --SUPPLIES--> Apple"


def test_format_common_neighbor_paths():
    row = {**TSMC, "relation": "SUPPLIES", "targets": [NVIDIA, APPLE]}
    assert format_common_neighbor_paths(row) == ["TSMC --SUPPLIES--> NVIDIA", "TSMC --SUPPLIES--> Apple"]


def test_graph_paths_for_result_semantic_route_is_empty():
    assert graph_paths_for_result({"route": "semantic", "chunks": []}) == []


def test_graph_paths_for_result_relational_neighbors():
    result = {
        "route": "relational", "pattern": "neighbors",
        "results": [{**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "in", "provenance": []}],
    }
    assert graph_paths_for_result(result) == ["TSMC --SUPPLIES--> NVIDIA"]


def test_graph_paths_for_result_graph_guided_hybrid():
    result = {
        "route": "graph_guided_hybrid",
        "edges": [{**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "in", "provenance": []}],
    }
    assert graph_paths_for_result(result) == ["TSMC --SUPPLIES--> NVIDIA"]


def test_graph_paths_for_result_dedupes_same_edge_seen_from_both_endpoints():
    # 1-hop expansion visits this edge once from NVIDIA (out) and once from TSMC (in) —
    # format_edge_path normalizes both to the identical subject-first string.
    result = {
        "route": "graph_guided_hybrid",
        "edges": [
            {**TSMC, "source": NVIDIA, "relation": "SUPPLIES", "direction": "in", "provenance": []},
            {**NVIDIA, "source": TSMC, "relation": "SUPPLIES", "direction": "out", "provenance": []},
        ],
    }
    assert graph_paths_for_result(result) == ["TSMC --SUPPLIES--> NVIDIA"]


def test_graph_provenance_chunk_ids_collects_from_results_and_edges():
    result = {
        "route": "relational",
        "results": [{"provenance": [{"source_chunk_id": "c1"}, {"source_chunk_id": "c2"}]}],
        "edges": [{"provenance": [{"source_chunk_id": "c3"}]}],
    }
    assert graph_provenance_chunk_ids(result) == {"c1", "c2", "c3"}


def test_chunk_citation_truncates_snippet_and_keeps_key_fields():
    chunk = {
        "doc_id": "d1", "chunk_id": "d1::0::0", "ticker": "NVDA", "form": "10-K",
        "section": "Item 1A", "source_url": "https://example.com", "text": "x" * 500, "score": 0.9,
    }
    citation = chunk_citation(chunk)
    assert citation["chunk_id"] == "d1::0::0"
    assert len(citation["snippet"]) == 300
    assert citation["score"] == 0.9
