"""Run the golden set end to end through the router + synthesis pipeline and score it.

Each golden question is routed and synthesized exactly like scripts/ask.py
does, then scored on: router accuracy (expected vs. actual route),
graph-path precision/recall (only for questions that carry a golden path —
see golden_set.py), and LLM-judged answer quality (faithfulness / answer
relevancy / context precision / correctness — see judge.py). Per-question
rows plus a rolled-up summary are returned so scripts/evaluate.py can print
or persist either without re-deriving them.
"""

from groq import Groq
from huggingface_hub import InferenceClient

from ..extraction.schema import Schema
from ..graph import GraphStore
from ..retrieval import VectorIndex
from ..router import EntityLookup, route_query
from ..synthesis import graph_paths_for_result, graph_provenance_chunk_ids, synthesize_answer
from .golden_set import GoldenQuestion
from .judge import DEFAULT_JUDGE_MODEL, judge_answer
from .path_metrics import path_precision_recall
from .router_metrics import router_accuracy


def _context_texts(result: dict, chunks_by_id: dict) -> list[str]:
    direct = result.get("chunks", [])
    direct_ids = {c["chunk_id"] for c in direct}
    graph_ids = graph_provenance_chunk_ids(result) - direct_ids
    graph_texts = [chunks_by_id[cid]["text"] for cid in graph_ids if cid in chunks_by_id]
    return [*(c["text"] for c in direct), *graph_texts]


def evaluate_question(
    question: GoldenQuestion,
    *,
    client: Groq,
    embedding_client: InferenceClient,
    schema: Schema,
    store: GraphStore,
    index: VectorIndex,
    chunks_by_id: dict,
    entity_lookup: EntityLookup,
    top_k: int = 5,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> dict:
    result = route_query(
        question.question, client=client, embedding_client=embedding_client, schema=schema, store=store, index=index,
        chunks_by_id=chunks_by_id, entity_lookup=entity_lookup, top_k=top_k,
    )
    synthesis = synthesize_answer(result, chunks_by_id=chunks_by_id, client=client)
    actual_paths = graph_paths_for_result(result)

    path_scores = (
        path_precision_recall(question.expected_graph_paths, actual_paths)
        if question.expected_graph_paths
        else None
    )
    judgment = judge_answer(
        question.question, synthesis["answer"], question.expected_answer,
        _context_texts(result, chunks_by_id), client=client, model_name=judge_model,
    )

    return {
        "id": question.id,
        "question": question.question,
        "expected_route": question.expected_route,
        "actual_route": result["route"],
        "route_correct": question.expected_route == result["route"],
        "answer": synthesis["answer"],
        "graph_paths": actual_paths,
        "path_scores": path_scores,
        "judgment": judgment.model_dump(),
    }


def run_evaluation(
    questions: list[GoldenQuestion],
    *,
    client: Groq,
    embedding_client: InferenceClient,
    schema: Schema,
    store: GraphStore,
    index: VectorIndex,
    chunks_by_id: dict,
    entity_lookup: EntityLookup,
    top_k: int = 5,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> dict:
    rows = [
        evaluate_question(
            q, client=client, embedding_client=embedding_client, schema=schema, store=store, index=index,
            chunks_by_id=chunks_by_id, entity_lookup=entity_lookup, top_k=top_k, judge_model=judge_model,
        )
        for q in questions
    ]
    return {"rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    def avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    path_rows = [r["path_scores"] for r in rows if r["path_scores"] is not None]

    return {
        "n_questions": len(rows),
        "router_accuracy": router_accuracy(
            [{"expected_route": r["expected_route"], "actual_route": r["actual_route"]} for r in rows]
        ),
        "path_precision": avg([p["precision"] for p in path_rows]),
        "path_recall": avg([p["recall"] for p in path_rows]),
        "path_f1": avg([p["f1"] for p in path_rows]),
        "faithfulness": avg([r["judgment"]["faithfulness"] for r in rows]),
        "answer_relevancy": avg([r["judgment"]["answer_relevancy"] for r in rows]),
        "context_precision": avg([r["judgment"]["context_precision"] for r in rows]),
        "correctness": avg([r["judgment"]["correctness"] for r in rows]),
    }
