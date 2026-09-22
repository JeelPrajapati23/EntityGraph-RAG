import pytest
from pydantic import ValidationError

from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.router.classify import ROUTES, build_classification_prompt, build_router_decision_model


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
