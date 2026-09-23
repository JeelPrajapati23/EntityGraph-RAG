"""Run the DepGraph router over eval/depgraph_questions.yaml and score it.

For each question: did the classifier pick the expected route (and pattern
/ relation), did every named entity resolve, and did the retrieved results
pass the question's graph-derived `expect` checks. One Groq call per
question, plus one embedding call when a route searches text.

Output: eval/results/depgraph_router.json

Usage:
    uv run python scripts/eval_depgraph_router.py [--ids exp-01,sem-02] [--variant NAME]
"""

import argparse
import json
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

from entitygraph_rag.depgraph import load_context, route_query
from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.llm_client import build_client
from entitygraph_rag.npm.advisory_index import DEFAULT_VARIANT, VARIANTS
from entitygraph_rag.retrieval import build_embedding_client

ROOT = Path(__file__).resolve().parent.parent
DEPGRAPH = ROOT / "data" / "processed" / "depgraph"
QUESTIONS = ROOT / "eval" / "depgraph_questions.yaml"
OUT_PATH = ROOT / "eval" / "results" / "depgraph_router.json"


def result_nodes(result: dict) -> set[str]:
    nodes = set()
    for row in result.get("results", []):
        nodes.update(v for k, v in row.items() if k in ("node_id", "project", "version_id") and isinstance(v, str))
        nodes.update(row.get("path", []))
    return nodes


def result_vulnerabilities(result: dict) -> set[str]:
    found = {row.get("vulnerability_id") for row in result.get("results", [])}
    found |= {row.get("node_id") for row in result.get("results", [])}
    found |= {a["vulnerability_id"] for a in result.get("advisories", []) if isinstance(a, dict)}
    return {f for f in found if f}


def check(expect: dict, result: dict, chunks_by_id: dict) -> list[str]:
    """Failed checks, as readable strings (empty = pass)."""
    failures = []
    if want := expect.get("vulnerabilities_include"):
        missing = set(want) - result_vulnerabilities(result)
        if missing:
            failures.append(f"missing advisories {sorted(missing)}")
    if want := expect.get("path"):
        if not any(row.get("path") == want for row in result.get("results", [])):
            failures.append(f"path not found: {' -> '.join(want)}")
    if want := expect.get("nodes_include"):
        missing = set(want) - result_nodes(result)
        if missing:
            failures.append(f"missing nodes {sorted(missing)}")
    if package := expect.get("chunks_affect_package"):
        chunks = result.get("chunks", [])
        stray = [c["chunk_id"] for c in chunks if package not in c.get("affected_packages", [])]
        if not chunks or stray:
            failures.append(f"chunks not about {package}: {stray or 'no chunks'}")
    if pattern := expect.get("top_chunk_matches"):
        chunks = result.get("chunks", [])
        top = chunks[0] if chunks else None
        if top is None or not re.search(pattern, f"{top.get('summary', '')}\n{top['text']}", re.IGNORECASE):
            failures.append(f"top chunk doesn't match /{pattern}/: {top['chunk_id'] if top else 'no chunks'}")
    return failures


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ids", default=None)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default=DEFAULT_VARIANT)
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    ctx = load_context(DEPGRAPH, build_embedding_client(), args.variant)
    schema = load_schema(ROOT / "schema" / "v2.yaml")
    client = build_client()

    rows = []
    for q in questions:
        result = route_query(q["question"], client=client, ctx=ctx, schema=schema)
        route_ok = result["route"] == q["route"]
        pattern_ok = q["route"] != "relational" or result["pattern"] == q.get("pattern")
        relation_ok = "relation" not in q or result["relation"] == q["relation"]
        failures = check(q.get("expect", {}), result, ctx.chunks_by_id)
        rows.append({"id": q["id"], "question": q["question"], "expected_route": q["route"],
                     "route": result["route"], "executed_route": result["executed_route"],
                     "pattern": result["pattern"], "relation": result["relation"],
                     "entities": result["entities"], "warnings": result["warnings"],
                     "route_ok": route_ok, "pattern_ok": pattern_ok and relation_ok,
                     "checks_ok": not failures, "failures": failures,
                     "reasoning": result["classification_reasoning"]})
        mark = "ok " if route_ok and pattern_ok and relation_ok and not failures else "BAD"
        print(f"{mark} {q['id']:8} {result['route']}/{result['pattern'] or '-'}"
              f"{'/' + result['relation'] if result['relation'] else ''}  "
              f"entities={[e['name'] for e in result['entities']]}"
              + (f"  failures={failures}" if failures else "")
              + (f"  warnings={result['warnings']}" if result["warnings"] else ""), flush=True)

    n = len(rows)
    summary = {
        "questions": n,
        "route_accuracy": sum(r["route_ok"] for r in rows) / n,
        "pattern_accuracy": sum(r["route_ok"] and r["pattern_ok"] for r in rows) / n,
        "checks_passed": sum(r["checks_ok"] for r in rows),
        "fully_correct": sum(r["route_ok"] and r["pattern_ok"] and r["checks_ok"] for r in rows),
        "variant": args.variant,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"summary": summary, "questions": rows}, indent=2), encoding="utf-8")
    print(f"\nroute {summary['route_accuracy']:.0%}, route+pattern {summary['pattern_accuracy']:.0%}, "
          f"checks passed {summary['checks_passed']}/{n}, fully correct {summary['fully_correct']}/{n} "
          f"-> {OUT_PATH.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
