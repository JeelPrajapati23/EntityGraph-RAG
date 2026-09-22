"""Turn a router result into the two citation shapes an answer needs.

Router/dispatch.py returns structured facts (entity ids/names, relation
types, confidence, edge provenance); this module only formats those into
readable graph-path strings (e.g. "NVIDIA --SUPPLIES--> TSMC") and chunk
citation records — no graph/index access happens here.
"""


def format_edge_path(row: dict) -> str:
    relation = row["relation"] or "MENTIONS"
    if row["direction"] == "out":
        return f"{row['source']['canonical_name']} --{relation}--> {row['canonical_name']}"
    return f"{row['canonical_name']} --{relation}--> {row['source']['canonical_name']}"


def format_two_hop_path(row: dict) -> str:
    first_relation = row["first_relation"] or "related to"
    return (
        f"{row['source']['canonical_name']} --{first_relation}--> {row['via']['canonical_name']} "
        f"--{row['relation']}--> {row['target']['canonical_name']}"
    )


def format_common_neighbor_paths(row: dict) -> list[str]:
    relation = row["relation"] or "related to"
    return [f"{row['canonical_name']} --{relation}--> {target['canonical_name']}" for target in row["targets"]]


def graph_paths_for_result(result: dict) -> list[str]:
    """Every human-readable graph-path string this router result supports, regardless of route.

    Deduplicated, order preserved: graph_guided_hybrid in particular visits
    the same edge from both endpoints during 1-hop expansion (once as an
    "out" edge from one query entity, once as an "in" edge from the other),
    and format_edge_path normalizes both to the same subject-first string.
    """
    if result["route"] == "relational":
        pattern = result.get("pattern", "neighbors")
        paths = []
        for row in result.get("results", []):
            if pattern == "common_neighbors":
                paths.extend(format_common_neighbor_paths(row))
            elif pattern == "two_hop":
                paths.append(format_two_hop_path(row))
            else:
                paths.append(format_edge_path(row))
        return list(dict.fromkeys(paths))

    if result["route"] == "graph_guided_hybrid":
        paths = [format_edge_path(row) for row in result.get("edges", [])]
        return list(dict.fromkeys(paths))

    return []  # semantic route retrieves no graph facts


def graph_provenance_chunk_ids(result: dict) -> set[str]:
    """Every source_chunk_id backing this result's graph facts (relational/hybrid routes)."""
    chunk_ids: set[str] = set()
    for row in result.get("results", []):
        chunk_ids.update(mention["source_chunk_id"] for mention in row.get("provenance", []))
    for row in result.get("edges", []):
        chunk_ids.update(mention["source_chunk_id"] for mention in row.get("provenance", []))
    return chunk_ids


def chunk_citation(chunk: dict) -> dict:
    return {
        "doc_id": chunk["doc_id"],
        "chunk_id": chunk["chunk_id"],
        "ticker": chunk["ticker"],
        "form": chunk["form"],
        "section": chunk["section"],
        "source_url": chunk["source_url"],
        "snippet": chunk["text"][:300],
        "score": chunk.get("score"),
    }
