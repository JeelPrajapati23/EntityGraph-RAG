from reachfix.conditions.merge import merge_conditions


def condition(osv_id, chunk, i, text, category="input_source", confidence=0.9):
    return {
        "relation": "EXPLOITABLE_WHEN", "extraction_method": "llm", "subject": osv_id,
        "condition_id": f"{osv_id}::{chunk}::{i}", "text": text, "category": category,
        "evidence": f"quote {chunk}.{i}", "evidence_match": "exact", "confidence": confidence,
        "source_chunk_id": f"{osv_id}::{chunk}", "source_doc_id": osv_id,
        "source_url": f"https://osv.dev/vulnerability/{osv_id}", "extracted_at": "2026-09-23T00:00:00+00:00",
    }


def test_near_duplicates_in_one_advisory_merge_keeping_the_most_confident():
    edges = [
        condition("GHSA-a", 0, 0, "Object.prototype is polluted by a co-dependency", "other", 0.9),
        condition("GHSA-a", 2, 0, "`Object.prototype` is polluted by a co-dependency.", "input_source", 0.95),
        condition("GHSA-a", 1, 0, "the application uses the Node.js http adapter", "platform"),
    ]

    nodes, merged = merge_conditions(edges)

    assert len(nodes) == 2
    polluted = next(e for e in merged if len(e["sources"]) == 2)
    node = next(n for n in nodes if n["node_id"] == polluted["object"])
    assert node["properties"]["category"] == "input_source"  # from the 0.95 member
    assert polluted["confidence"] == 0.95
    assert {s["source_chunk_id"] for s in polluted["sources"]} == {"GHSA-a::0", "GHSA-a::2"}


def test_conditions_are_never_merged_across_advisories():
    edges = [condition("GHSA-a", 0, 0, "the application parses untrusted YAML"),
             condition("GHSA-b", 0, 0, "the application parses untrusted YAML")]

    nodes, merged = merge_conditions(edges)

    assert [n["node_id"] for n in nodes] == ["GHSA-a::cond::0", "GHSA-b::cond::0"]
    assert [(e["subject"], e["object"]) for e in merged] == [("GHSA-a", "GHSA-a::cond::0"), ("GHSA-b", "GHSA-b::cond::0")]


def test_distinct_conditions_stay_separate():
    edges = [condition("GHSA-a", 0, 0, "the `maxRedirects` option is raised"),
             condition("GHSA-a", 0, 1, "the `beforeRedirect` hook is set")]
    nodes, _ = merge_conditions(edges)
    assert len(nodes) == 2
