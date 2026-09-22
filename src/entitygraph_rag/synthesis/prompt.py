"""Build the answer-synthesis prompt: retrieved chunks + graph paths -> a cited answer.

Takes full chunk records (chunks, with a "text" field), not the truncated
citation snippets from citations.py — those are a display preview for the
returned citation block, not evidence for the model to reason over. Feeding
the model a truncated snippet risks cutting off the very fact that answers
the question (found live: a chunk whose 380-char text put "Chief Financial
Officer" past a 300-char cutoff, so the model correctly refused to answer
from what little it could see).
"""


def build_synthesis_prompt(query: str, *, chunks: list[dict], graph_paths: list[str]) -> str:
    chunk_block = (
        "\n\n".join(
            f"[chunk {i}] ({c['ticker']} {c['form']}, {c['section']}, doc {c['doc_id']})\n{c['text']}"
            for i, c in enumerate(chunks, start=1)
        )
        or "(no document chunks retrieved)"
    )
    path_block = "\n".join(f"- {path}" for path in graph_paths) or "(no graph relations retrieved)"

    return f"""Answer the user's question using ONLY the evidence below — do not use \
outside knowledge. Cite document claims with [chunk N] and reference graph \
relations by name where they support your answer. If the evidence doesn't \
answer the question, say so plainly rather than guessing.

Question: {query}

Graph relations retrieved:
{path_block}

Document chunks retrieved:
{chunk_block}

Answer:"""
