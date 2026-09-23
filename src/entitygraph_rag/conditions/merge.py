"""Merge near-duplicate EXPLOITABLE_WHEN conditions within each advisory.

A multi-chunk advisory often states the same precondition in several
chunks, in slightly different words. Conditions of one advisory whose
normalized text scores at least MERGE_THRESHOLD (rapidfuzz
token_sort_ratio) against an existing one join it. The merged node keeps
the text and category of its highest-confidence member and lists every
member's chunk and evidence as sources.

Conditions are never merged across advisories: "untrusted input" in two
advisories may mean different inputs, and a wrong merge would link
unrelated vulnerabilities.
"""

import re
from collections import defaultdict

from rapidfuzz import fuzz

MERGE_THRESHOLD = 90
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_condition(text: str) -> str:
    return _NON_WORD_RE.sub(" ", text.lower()).strip()


def condition_node_id(osv_id: str, index: int) -> str:
    return f"{osv_id}::cond::{index}"


def merge_conditions(edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (ExploitCondition nodes, one EXPLOITABLE_WHEN edge per node)."""
    by_advisory: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        by_advisory[edge["subject"]].append(edge)

    nodes, merged_edges = [], []
    for osv_id in sorted(by_advisory):
        clusters: list[list[dict]] = []
        for edge in sorted(by_advisory[osv_id], key=lambda e: -e["confidence"]):
            key = normalize_condition(edge["text"])
            for cluster in clusters:
                if fuzz.token_sort_ratio(key, normalize_condition(cluster[0]["text"])) >= MERGE_THRESHOLD:
                    cluster.append(edge)
                    break
            else:
                clusters.append([edge])

        for index, cluster in enumerate(clusters):
            top = cluster[0]
            node_id = condition_node_id(osv_id, index)
            nodes.append({
                "node_id": node_id,
                "node_type": "ExploitCondition",
                "name": top["text"],
                "aliases": sorted({e["text"] for e in cluster}),
                "properties": {"text": top["text"], "category": top["category"]},
            })
            merged_edges.append({
                "relation": top["relation"],
                "extraction_method": "llm",
                "subject": osv_id,
                "object": node_id,
                "confidence": top["confidence"],
                "source_doc_id": osv_id,
                "source_url": top["source_url"],
                "source_chunk_id": top["source_chunk_id"],
                "extracted_at": top["extracted_at"],
                "sources": [
                    {k: e[k] for k in ("condition_id", "source_chunk_id", "evidence", "evidence_match", "confidence")}
                    for e in cluster
                ],
            })
    return nodes, merged_edges
