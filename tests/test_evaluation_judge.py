import json
from types import SimpleNamespace

from entitygraph_rag.evaluation.judge import AnswerJudgment, build_judge_prompt, judge_answer

FAKE_JUDGMENT = {
    "faithfulness": 0.9,
    "answer_relevancy": 0.8,
    "context_precision": 0.7,
    "correctness": 1.0,
    "reasoning": "Matches the reference answer and is grounded in the context.",
}


class _FakeModels:
    def generate_content(self, *, model, contents, config):
        self.last_prompt = contents
        self.last_config = config
        return SimpleNamespace(text=json.dumps(FAKE_JUDGMENT))


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def test_build_judge_prompt_includes_question_answer_reference_and_context():
    prompt = build_judge_prompt("who supplies NVIDIA?", "TSMC supplies NVIDIA.", "TSMC.", ["TSMC fabricates chips for NVIDIA."])

    assert "who supplies NVIDIA?" in prompt
    assert "TSMC supplies NVIDIA." in prompt
    assert "TSMC fabricates chips for NVIDIA." in prompt


def test_build_judge_prompt_handles_no_context():
    prompt = build_judge_prompt("q", "a", "ref", [])
    assert "(no context retrieved)" in prompt


def test_judge_answer_parses_structured_response():
    client = _FakeClient()

    judgment = judge_answer("q", "a", "ref", ["context chunk"], client=client)

    assert isinstance(judgment, AnswerJudgment)
    assert judgment.faithfulness == 0.9
    assert judgment.correctness == 1.0
    assert client.models.last_config.response_schema is AnswerJudgment
