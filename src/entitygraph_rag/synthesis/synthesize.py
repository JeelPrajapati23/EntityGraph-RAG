"""Turn a router result into a natural-language answer plus a structured citation block.

The citation block (chunk snippets + graph paths) is returned alongside the
prose answer, not folded into it — callers render it as its own
"show reasoning" section rather than trusting the LLM to cite perfectly
inline (see project plan, Phase 5).
"""

from google import genai

from .citations import chunk_citation, graph_paths_for_result, graph_provenance_chunk_ids
from .prompt import build_synthesis_prompt

DEFAULT_SYNTHESIS_MODEL = "gemini-2.5-flash"


def synthesize_answer(
    result: dict,
    *,
    chunks_by_id: dict,
    client: genai.Client,
    model_name: str = DEFAULT_SYNTHESIS_MODEL,
) -> dict:
    query = result["query"]

    direct_chunks = result.get("chunks", [])
    direct_chunk_ids = {chunk["chunk_id"] for chunk in direct_chunks}
    graph_chunk_ids = graph_provenance_chunk_ids(result) - direct_chunk_ids
    graph_chunks = [chunks_by_id[chunk_id] for chunk_id in graph_chunk_ids if chunk_id in chunks_by_id]

    all_chunks = [*direct_chunks, *graph_chunks]
    chunk_citations = [chunk_citation(chunk) for chunk in all_chunks]
    graph_paths = graph_paths_for_result(result)

    # The model reasons over full chunk text; chunk_citations' truncated
    # "snippet" is a display preview for the returned citation block only.
    prompt = build_synthesis_prompt(query, chunks=all_chunks, graph_paths=graph_paths)
    response = client.models.generate_content(model=model_name, contents=prompt)

    return {
        "query": query,
        "route": result["route"],
        "answer": response.text,
        "citations": {"chunks": chunk_citations, "graph_paths": graph_paths},
    }
