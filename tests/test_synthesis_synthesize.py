from types import SimpleNamespace

from reachfix.synthesis.synthesize import synthesize_answer

CHUNK_A = {
    "chunk_id": "d1::0::0", "doc_id": "d1", "ticker": "NVDA", "form": "10-K",
    "section": "Item 1", "source_url": "u", "text": "TSMC fabricates chips for NVIDIA.", "score": 0.9,
}
CHUNK_B = {
    "chunk_id": "d1::0::1", "doc_id": "d1", "ticker": "NVDA", "form": "10-K",
    "section": "Item 1", "source_url": "u", "text": "Colette Kress is CFO.",
}


class _FakeCompletions:
    def create(self, *, model, messages, temperature):
        self.last_messages = messages
        message = SimpleNamespace(content="This is the synthesized answer.")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def test_synthesize_answer_semantic_route_uses_direct_chunks():
    result = {"route": "semantic", "query": "what risks does NVIDIA face?", "chunks": [CHUNK_A]}
    client = _FakeClient()

    synthesis = synthesize_answer(result, chunks_by_id={}, client=client)

    assert synthesis["answer"] == "This is the synthesized answer."
    assert synthesis["route"] == "semantic"
    assert [c["chunk_id"] for c in synthesis["citations"]["chunks"]] == ["d1::0::0"]
    assert synthesis["citations"]["graph_paths"] == []
    assert "TSMC fabricates chips for NVIDIA." in client.chat.completions.last_messages[-1]["content"]


def test_synthesize_answer_relational_route_pulls_in_provenance_chunks():
    result = {
        "route": "relational", "query": "who is NVIDIA's CFO?", "pattern": "neighbors",
        "results": [
            {
                "entity_id": "Person:colette", "canonical_name": "Colette Kress",
                "source": {"entity_id": "Company:nvidia", "canonical_name": "NVIDIA"},
                "relation": "EXECUTIVE_OF", "direction": "in", "confidence": 0.98,
                "provenance": [{"source_chunk_id": "d1::0::1", "source_doc_id": "d1", "confidence": 0.98, "extracted_at": "t"}],
            }
        ],
    }
    client = _FakeClient()

    synthesis = synthesize_answer(result, chunks_by_id={"d1::0::1": CHUNK_B}, client=client)

    assert synthesis["citations"]["graph_paths"] == ["Colette Kress --EXECUTIVE_OF--> NVIDIA"]
    assert [c["chunk_id"] for c in synthesis["citations"]["chunks"]] == ["d1::0::1"]


def test_synthesize_answer_does_not_duplicate_chunk_present_in_both_direct_and_graph_provenance():
    result = {
        "route": "graph_guided_hybrid", "query": "q", "chunks": [CHUNK_A],
        "edges": [
            {
                "entity_id": "x", "canonical_name": "x", "source": {"entity_id": "y", "canonical_name": "y"},
                "relation": "MENTIONS", "direction": "out",
                "provenance": [{"source_chunk_id": "d1::0::0", "source_doc_id": "d1", "confidence": 0.5, "extracted_at": "t"}],
            }
        ],
    }
    client = _FakeClient()

    synthesis = synthesize_answer(result, chunks_by_id={"d1::0::0": CHUNK_A}, client=client)

    assert [c["chunk_id"] for c in synthesis["citations"]["chunks"]] == ["d1::0::0"]  # not duplicated
