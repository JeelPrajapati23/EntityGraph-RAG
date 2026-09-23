"""Turn DepGraph nodes and edge files into GraphStore entities and edges.

The GraphStore interface is shared with the finance pipeline, so nodes use
its entity shape (entity_id, entity_type, canonical_name, aliases) with the
schema properties under `properties`. Edges become subject_id / relation /
object_id, with a `provenance` list and the remaining fields as
`properties`.

A DEPENDS_ON fact seen in several lockfiles, and confirmed by the
registry, is one edge whose provenance lists each lockfile plus the
registry packument. This is the plan's "dedupe, carrying both sources as
provenance".
"""

from .nodes import dependency_edge_endpoints
from .registry import packument_url

LOCKFILE_DOC_PREFIX = "lockfile:npm:"
# Fields that describe where an edge came from rather than what it says.
_PROVENANCE_KEYS = {"relation", "subject", "object", "extraction_method", "source_doc_id", "source_url",
                    "source_chunk_id", "confidence", "extracted_at", "sources"}


def root_of_lockfile(lockfile_doc_id: str) -> str:
    """"lockfile:npm:express@4.17.1" -> "npm:express@4.17.1" (see scripts/fetch_lockfiles.py)."""
    if not lockfile_doc_id.startswith(LOCKFILE_DOC_PREFIX):
        raise ValueError(f"not a lockfile doc id: {lockfile_doc_id!r}")
    return "npm:" + lockfile_doc_id[len(LOCKFILE_DOC_PREFIX):]


def to_entity(node: dict) -> dict:
    return {
        "entity_id": node["node_id"],
        "entity_type": node["node_type"],
        "canonical_name": node["name"],
        "aliases": node["aliases"],
        "properties": node["properties"],
    }


def _graph_edge(edge: dict, provenance: list[dict], drop: set[str] = frozenset()) -> dict:
    return {
        "subject_id": edge["subject"],
        "object_id": edge["object"],
        "relation": edge["relation"],
        "confidence": edge.get("confidence", 1.0),
        "provenance": provenance,
        "properties": {k: v for k, v in edge.items() if k not in _PROVENANCE_KEYS | drop},
    }


def dependency_to_edge(row: dict) -> dict:
    """A dependency_edges.jsonl row: one provenance entry per lockfile, plus the registry if it agrees."""
    edge = dependency_edge_endpoints(row)
    provenance = [{"source_doc_id": doc_id, "extraction_method": "deterministic", "confidence": 1.0}
                  for doc_id in row["lockfile_doc_ids"]]
    if row["registry_check"] == "match":
        provenance.append({"source_doc_id": f"npm-registry:{row['from_name']}",
                           "source_url": packument_url(row["from_name"]),
                           "extraction_method": "deterministic", "confidence": 1.0})
    # Endpoint names/versions are already in the node ids.
    return _graph_edge(edge, provenance, drop={"from_name", "from_version", "to_name", "to_version"})


def record_to_edge(row: dict) -> dict:
    """A vulnerability/registry/condition edge row. Merged conditions list one provenance entry per source chunk."""
    base = {k: row[k] for k in ("source_doc_id", "source_url", "extraction_method", "extracted_at") if k in row}
    if "sources" in row:
        provenance = [{**base, "source_chunk_id": s["source_chunk_id"], "confidence": s["confidence"],
                       "evidence": s["evidence"], "evidence_match": s["evidence_match"]} for s in row["sources"]]
    else:
        provenance = [{**base, "confidence": row.get("confidence", 1.0)}]
    return _graph_edge(row, provenance)
