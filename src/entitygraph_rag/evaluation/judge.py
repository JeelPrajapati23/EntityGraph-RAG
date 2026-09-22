"""LLM-judge answer-quality scoring: RAGAS-inspired, hand-rolled against Groq JSON mode.

The project plan calls for reusing RAGAS for the vector-retrieval half of
evaluation, but RAGAS is built around LangChain/OpenAI and would need a
custom LLM wrapper to run against this project's LLM provider — a heavy
dependency for what the rest of this codebase does with a single JSON-mode
call (see router/classify.py, extraction/schema.py). Instead this scores
the same dimensions by hand: faithfulness, answer relevancy and context
precision (RAGAS's vector-retrieval trio), plus correctness against the
golden question's known-correct reference answer (the project plan's
"known correct answer" requirement) — all four in one judge call per
question to keep evaluation API cost down.
"""

from groq import Groq
from pydantic import BaseModel

from ..llm_client import DEFAULT_MODEL, generate_json

DEFAULT_JUDGE_MODEL = DEFAULT_MODEL


class AnswerJudgment(BaseModel):
    faithfulness: float  # every claim in the answer is supported by the given context
    answer_relevancy: float  # the answer actually addresses the question asked
    context_precision: float  # fraction of the given context that is relevant to the question
    correctness: float  # the answer agrees with the known-correct reference answer
    reasoning: str


def build_judge_prompt(question: str, answer: str, reference_answer: str, context_chunks: list[str]) -> str:
    context_block = "\n\n".join(f"[{i + 1}] {text}" for i, text in enumerate(context_chunks)) or "(no context retrieved)"

    return f"""You are grading a RAG system's answer. Score four dimensions, each a \
float from 0.0 to 1.0:

- faithfulness: what fraction of the answer's claims are directly supported \
by the retrieved context below? (1.0 = every claim is grounded, 0.0 = none are)
- answer_relevancy: does the answer actually address the question asked, \
regardless of factual correctness? (1.0 = fully on-topic and responsive)
- context_precision: what fraction of the context chunks below are actually \
relevant to answering the question? (1.0 = every chunk is relevant, 0.0 = none are)
- correctness: does the answer agree with the known-correct reference answer \
below, in substance (not exact wording)? (1.0 = fully agrees, 0.0 = contradicts \
or misses it entirely)

Question: {question}

Reference answer (known correct): {reference_answer}

System's answer: {answer}

Retrieved context:
{context_block}

Return only a JSON object with exactly these keys: "faithfulness" (float), \
"answer_relevancy" (float), "context_precision" (float), "correctness" \
(float), "reasoning" (string)."""


def judge_answer(
    question: str,
    answer: str,
    reference_answer: str,
    context_chunks: list[str],
    *,
    client: Groq,
    model_name: str = DEFAULT_JUDGE_MODEL,
) -> AnswerJudgment:
    raw_json = generate_json(
        client, user_prompt=build_judge_prompt(question, answer, reference_answer, context_chunks), model_name=model_name,
    )
    return AnswerJudgment.model_validate_json(raw_json)
