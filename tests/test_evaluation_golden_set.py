import pytest
from pydantic import ValidationError

from entitygraph_rag.evaluation.golden_set import GoldenQuestion, load_golden_set


def test_load_golden_set_parses_every_entry(tmp_path):
    path = tmp_path / "golden_set.yaml"
    path.write_text(
        """
questions:
  - id: q1
    expected_route: relational
    question: "who supplies NVIDIA?"
    expected_answer: "TSMC supplies NVIDIA."
    expected_graph_paths:
      - "TSMC --SUPPLIES--> NVIDIA"
  - id: q2
    expected_route: semantic
    question: "what risks does NVIDIA face?"
    expected_answer: "Supply chain concentration."
""",
        encoding="utf-8",
    )

    questions = load_golden_set(path)

    assert [q.id for q in questions] == ["q1", "q2"]
    assert questions[0].expected_graph_paths == ["TSMC --SUPPLIES--> NVIDIA"]
    assert questions[1].expected_graph_paths == []  # defaults to empty, not required in the file
    assert questions[1].notes is None


def test_golden_question_rejects_unknown_route():
    with pytest.raises(ValidationError):
        GoldenQuestion(id="q1", expected_route="keyword_search", question="q", expected_answer="a")
