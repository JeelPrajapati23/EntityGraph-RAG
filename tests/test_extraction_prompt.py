from reachfix.extraction.prompt import build_system_prompt, build_user_prompt
from reachfix.extraction.schema import load_schema


def test_system_prompt_names_every_node_and_edge_type():
    schema = load_schema()
    prompt = build_system_prompt(schema)

    for node_name in schema.node_types:
        assert node_name in prompt
    for edge_name in schema.edge_types:
        assert edge_name in prompt


def test_user_prompt_includes_chunk_text():
    assert "TSMC fabricates chips for NVIDIA." in build_user_prompt("TSMC fabricates chips for NVIDIA.")
