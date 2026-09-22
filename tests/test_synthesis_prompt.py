from entitygraph_rag.synthesis.prompt import build_synthesis_prompt


def test_prompt_includes_query_chunks_and_paths():
    prompt = build_synthesis_prompt(
        "who supplies NVIDIA?",
        chunks=[{"ticker": "NVDA", "form": "10-K", "section": "Item 1", "doc_id": "d1", "text": "TSMC fabricates chips for NVIDIA, in full."}],
        graph_paths=["TSMC --SUPPLIES--> NVIDIA"],
    )
    assert "who supplies NVIDIA?" in prompt
    assert "[chunk 1]" in prompt
    assert "TSMC fabricates chips for NVIDIA, in full." in prompt
    assert "TSMC --SUPPLIES--> NVIDIA" in prompt


def test_prompt_uses_full_text_not_a_truncated_snippet():
    long_text = "x" * 500
    prompt = build_synthesis_prompt(
        "q", chunks=[{"ticker": "NVDA", "form": "10-K", "section": "s", "doc_id": "d1", "text": long_text}], graph_paths=[]
    )
    assert long_text in prompt


def test_prompt_handles_no_evidence_gracefully():
    prompt = build_synthesis_prompt("anything?", chunks=[], graph_paths=[])
    assert "no document chunks retrieved" in prompt
    assert "no graph relations retrieved" in prompt
