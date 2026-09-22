"""Run the golden set (eval/golden_set.yaml) through the full pipeline and report scores.

Loads every artifact the pipeline produces (same as scripts/ask.py), runs
each golden question through route_query + synthesize_answer, scores router
accuracy, graph-path precision/recall, and LLM-judged answer quality, then
prints a per-question table and the aggregate summary. Pass --out to also
write the full per-question results (including judge reasoning) as JSON.

Usage:
    uv run python scripts/evaluate.py
    uv run python scripts/evaluate.py --out eval/results/latest.json
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from entitygraph_rag.evaluation import load_golden_set, run_evaluation
from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.graph import NetworkXGraphStore
from entitygraph_rag.llm_client import build_client
from entitygraph_rag.retrieval import VectorIndex, build_embedding_client
from entitygraph_rag.router import EntityLookup

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.jsonl"
ENTITIES_PATH = ROOT / "data" / "processed" / "entities.jsonl"
GRAPH_PATH = ROOT / "data" / "processed" / "graph.pkl"
INDEX_PATH = ROOT / "data" / "processed" / "chunk_index"
GOLDEN_SET_PATH = ROOT / "eval" / "golden_set.yaml"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def print_report(evaluation: dict) -> None:
    print(f"{'id':<8} {'route (exp/actual)':<38} {'path P/R/F1':<18} judge (faith/rel/ctx/correct)")
    for row in evaluation["rows"]:
        route_flag = "OK" if row["route_correct"] else "X "
        route_col = f"{row['expected_route']} / {row['actual_route']} [{route_flag}]"
        if row["path_scores"]:
            p = row["path_scores"]
            path_col = f"{p['precision']:.2f}/{p['recall']:.2f}/{p['f1']:.2f}"
        else:
            path_col = "-"
        j = row["judgment"]
        judge_col = f"{j['faithfulness']:.2f}/{j['answer_relevancy']:.2f}/{j['context_precision']:.2f}/{j['correctness']:.2f}"
        print(f"{row['id']:<8} {route_col:<38} {path_col:<18} {judge_col}")

    s = evaluation["summary"]
    print(f"\n{s['n_questions']} questions, router accuracy: {s['router_accuracy']:.0%}")

    def fmt(value: float | None) -> str:
        return f"{value:.3f}" if value is not None else "n/a"

    print(f"path precision/recall/f1: {fmt(s['path_precision'])} / {fmt(s['path_recall'])} / {fmt(s['path_f1'])}")
    print(
        f"faithfulness: {fmt(s['faithfulness'])}  answer_relevancy: {fmt(s['answer_relevancy'])}  "
        f"context_precision: {fmt(s['context_precision'])}  correctness: {fmt(s['correctness'])}"
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-set", type=Path, default=GOLDEN_SET_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", type=Path, default=None, help="write full per-question results as JSON")
    args = parser.parse_args()

    missing = [p for p in (CHUNKS_PATH, ENTITIES_PATH, GRAPH_PATH) if not p.exists()]
    if missing:
        names = ", ".join(p.relative_to(ROOT).as_posix() for p in missing)
        raise SystemExit(f"missing required file(s): {names} — run build_chunks/resolve_entities/build_graph first")

    chunks_by_id = {c["chunk_id"]: c for c in load_jsonl(CHUNKS_PATH)}
    entities = load_jsonl(ENTITIES_PATH)
    store = NetworkXGraphStore.from_file(GRAPH_PATH)
    index = VectorIndex.from_file(INDEX_PATH)
    entity_lookup = EntityLookup(entities)
    schema = load_schema()
    client = build_client()
    embedding_client = build_embedding_client()

    questions = load_golden_set(args.golden_set)
    evaluation = run_evaluation(
        questions, client=client, embedding_client=embedding_client, schema=schema, store=store, index=index,
        chunks_by_id=chunks_by_id, entity_lookup=entity_lookup, top_k=args.top_k,
    )

    print_report(evaluation)

    if args.out:
        out_path = args.out if args.out.is_absolute() else ROOT / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
        print(f"\nWrote full results to {out_path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
