from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from reachfix.extraction.schema import load_schema
from reachfix.router.classify import ROUTES, build_classification_prompt, build_router_decision_model
from reachfix.router.router import FALLBACK_REASONING, classify_query


@pytest.fixture(scope="module")
def schema():
    return load_schema()


def test_prompt_names_every_route_and_relation(schema):
    prompt = build_classification_prompt(schema)
    for route in ROUTES:
        assert route in prompt
    for relation_name in schema.edge_types:
        assert relation_name in prompt


def test_decision_model_accepts_minimal_semantic_decision(schema):
    RouterDecision = build_router_decision_model(schema)
    decision = RouterDecision(route="semantic", entities=[], reasoning="factual question")
    assert decision.relation is None
    assert decision.graph_pattern is None


def test_decision_model_accepts_full_relational_decision(schema):
    RouterDecision = build_router_decision_model(schema)
    decision = RouterDecision(
        route="relational", entities=["NVIDIA"], relation="SUPPLIES", graph_pattern="neighbors",
        reasoning="asks who supplies NVIDIA",
    )
    assert decision.relation == "SUPPLIES"


def test_decision_model_rejects_unknown_route(schema):
    RouterDecision = build_router_decision_model(schema)
    with pytest.raises(ValidationError):
        RouterDecision(route="keyword_search", entities=[], reasoning="x")


def test_decision_model_rejects_unknown_relation(schema):
    RouterDecision = build_router_decision_model(schema)
    with pytest.raises(ValidationError):
        RouterDecision(route="relational", entities=["NVIDIA"], relation="MANUFACTURES_FOR", reasoning="x")


class _FakeGroq:
    """Returns canned completion texts in order, one per call."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        content = self._responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


VALID = '{"route": "relational", "entities": ["NVIDIA"], "relation": "SUPPLIES", "graph_pattern": "neighbors", "reasoning": "r"}'
MISSPELLED = '{"route": "relational", "entities": ["NVIDIA"], "relation": "DISLOSED_RISK", "graph_pattern": "neighbors", "reasoning": "r"}'


def test_classify_query_retries_once_after_invalid_output(schema):
    client = _FakeGroq(MISSPELLED, VALID)
    decision = classify_query("who supplies NVIDIA?", client=client, schema=schema)
    assert client.calls == 2
    assert decision.relation == "SUPPLIES"


def test_classify_query_falls_back_to_semantic_after_two_failures(schema):
    client = _FakeGroq(MISSPELLED, "not json at all")
    decision = classify_query("who supplies NVIDIA?", client=client, schema=schema)
    assert client.calls == 2
    assert decision.route == "semantic"
    assert decision.entities == []
    assert decision.reasoning == FALLBACK_REASONING
