import reachfix.evaluation.runner as runner_module
from reachfix.evaluation.golden_set import GoldenQuestion
from reachfix.evaluation.judge import AnswerJudgment
from reachfix.evaluation.runner import evaluate_question, run_evaluation

CHUNK_A = {"chunk_id": "c1", "text": "TSMC fabricates chips for NVIDIA.", "score": 0.9}

RELATIONAL_QUESTION = GoldenQuestion(
    id="rel-01",
    expected_route="relational",
    question="who supplies NVIDIA?",
    expected_answer="TSMC supplies NVIDIA.",
    expected_graph_paths=["TSMC --SUPPLIES--> NVIDIA"],
)

SEMANTIC_QUESTION = GoldenQuestion(
    id="sem-01",
    expected_route="semantic",
    question="what risks does NVIDIA face?",
    expected_answer="Supply chain concentration.",
)

FAKE_JUDGMENT = AnswerJudgment(faithfulness=0.9, answer_relevancy=0.8, context_precision=0.7, correctness=1.0, reasoning="ok")


def _patch_pipeline(monkeypatch, *, route_result: dict, actual_route: str):
    monkeypatch.setattr(runner_module, "route_query", lambda *a, **k: {**route_result, "route": actual_route})
    monkeypatch.setattr(runner_module, "synthesize_answer", lambda *a, **k: {"answer": "synthesized answer"})
    monkeypatch.setattr(runner_module, "judge_answer", lambda *a, **k: FAKE_JUDGMENT)


def test_evaluate_question_relational_route_matches_and_scores_paths(monkeypatch):
    route_result = {"pattern": "neighbors", "results": [
        {
            "entity_id": "Company:tsmc", "canonical_name": "TSMC",
            "source": {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA"},
            "relation": "SUPPLIES", "direction": "in", "confidence": 0.9, "provenance": [],
        }
    ]}
    _patch_pipeline(monkeypatch, route_result=route_result, actual_route="relational")

    row = evaluate_question(
        RELATIONAL_QUESTION, client=None, embedding_client=None, schema=None, store=None, index=None, chunks_by_id={}, entity_lookup=None,
    )

    assert row["route_correct"] is True
    assert row["graph_paths"] == ["TSMC --SUPPLIES--> NVIDIA"]
    assert row["path_scores"]["precision"] == 1.0
    assert row["path_scores"]["recall"] == 1.0
    assert row["judgment"]["correctness"] == 1.0


def test_evaluate_question_semantic_route_has_no_path_scores(monkeypatch):
    _patch_pipeline(monkeypatch, route_result={"chunks": [CHUNK_A]}, actual_route="semantic")

    row = evaluate_question(
        SEMANTIC_QUESTION, client=None, embedding_client=None, schema=None, store=None, index=None, chunks_by_id={}, entity_lookup=None,
    )

    assert row["route_correct"] is True
    assert row["path_scores"] is None


def test_evaluate_question_flags_route_mismatch(monkeypatch):
    _patch_pipeline(monkeypatch, route_result={"chunks": []}, actual_route="graph_guided_hybrid")

    row = evaluate_question(
        SEMANTIC_QUESTION, client=None, embedding_client=None, schema=None, store=None, index=None, chunks_by_id={}, entity_lookup=None,
    )

    assert row["route_correct"] is False
    assert row["actual_route"] == "graph_guided_hybrid"


def test_run_evaluation_aggregates_summary_across_questions(monkeypatch):
    monkeypatch.setattr(
        runner_module,
        "evaluate_question",
        lambda q, **k: {
            "id": q.id,
            "expected_route": q.expected_route,
            "actual_route": q.expected_route,
            "route_correct": True,
            "path_scores": {"precision": 1.0, "recall": 1.0, "f1": 1.0} if q.expected_graph_paths else None,
            "judgment": {"faithfulness": 1.0, "answer_relevancy": 1.0, "context_precision": 1.0, "correctness": 1.0},
        },
    )

    evaluation = run_evaluation(
        [RELATIONAL_QUESTION, SEMANTIC_QUESTION],
        client=None, embedding_client=None, schema=None, store=None, index=None, chunks_by_id={}, entity_lookup=None,
    )

    assert evaluation["summary"]["n_questions"] == 2
    assert evaluation["summary"]["router_accuracy"] == 1.0
    assert evaluation["summary"]["path_precision"] == 1.0  # only rel-01 has a path score, its own average
    assert evaluation["summary"]["faithfulness"] == 1.0
