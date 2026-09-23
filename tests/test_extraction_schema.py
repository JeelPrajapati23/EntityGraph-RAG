import pytest
from pydantic import ValidationError

from reachfix.extraction.schema import build_triple_model, load_schema, validate_triple


@pytest.fixture(scope="module")
def schema():
    return load_schema()


def test_load_schema_parses_node_and_edge_types(schema):
    assert schema.version == 1
    assert "Company" in schema.node_types
    assert "SUPPLIES" in schema.edge_types
    assert schema.edge_types["SUPPLIES"].subject_types == ["Company"]
    assert schema.edge_types["SUPPLIES"].object_types == ["Company"]


def test_load_schema_normalizes_list_valued_object(schema):
    # MENTIONS is the one edge type with a multi-type object in schema/v1.yaml
    mentions = schema.edge_types["MENTIONS"]
    assert set(mentions.object_types) == {"Company", "Person", "Product", "Location"}


def test_triple_model_accepts_valid_triple(schema):
    Triple = build_triple_model(schema)
    triple = Triple(
        subject="TSMC",
        subject_type="Company",
        relation="SUPPLIES",
        object="NVIDIA",
        object_type="Company",
        confidence=0.9,
    )
    assert triple.relation == "SUPPLIES"


def test_triple_model_rejects_unknown_relation(schema):
    Triple = build_triple_model(schema)
    with pytest.raises(ValidationError):
        Triple(
            subject="TSMC",
            subject_type="Company",
            relation="MANUFACTURES_FOR",  # not in schema/v1.yaml
            object="NVIDIA",
            object_type="Company",
            confidence=0.9,
        )


def test_triple_model_rejects_unknown_node_type(schema):
    Triple = build_triple_model(schema)
    with pytest.raises(ValidationError):
        Triple(
            subject="TSMC",
            subject_type="Organization",  # not in schema/v1.yaml
            relation="SUPPLIES",
            object="NVIDIA",
            object_type="Company",
            confidence=0.9,
        )


def test_validate_triple_accepts_correct_subject_object_types(schema):
    Triple = build_triple_model(schema)
    triple = Triple(
        subject="TSMC", subject_type="Company", relation="SUPPLIES",
        object="NVIDIA", object_type="Company", confidence=0.9,
    )
    assert validate_triple(schema, triple) is None


def test_validate_triple_rejects_wrong_object_type_for_relation(schema):
    # AUDITED_BY requires object_type=Auditor; the model layer allows any
    # node type in that field, so this mismatch must be caught here instead.
    Triple = build_triple_model(schema)
    triple = Triple(
        subject="NVIDIA", subject_type="Company", relation="AUDITED_BY",
        object="Jensen Huang", object_type="Person", confidence=0.7,
    )
    reason = validate_triple(schema, triple)
    assert reason is not None
    assert "AUDITED_BY" in reason


def test_validate_triple_accepts_any_mentions_object_type(schema):
    Triple = build_triple_model(schema)
    for object_type in ("Company", "Person", "Product", "Location"):
        triple = Triple(
            subject="NVIDIA", subject_type="Company", relation="MENTIONS",
            object="x", object_type=object_type, confidence=0.5,
        )
        assert validate_triple(schema, triple) is None
