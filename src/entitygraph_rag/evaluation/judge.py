"""LLM-judge answer-quality scoring: RAGAS-inspired, hand-rolled against Gemini structured output.

The project plan calls for reusing RAGAS for the vector-retrieval half of
evaluation, but RAGAS is built around LangChain/OpenAI and would need a
custom LLM wrapper to run against Gemini — a heavy dependency for what the
rest of this codebase does with a single structured-output call (see
router/classify.py, extraction/schema.py). Instead this scores the same
dimensions by hand: faithfulness, answer relevancy and context precision
(RAGAS's vector-retrieval trio), plus correctness against the golden
question's known-correct reference answer (the project plan's "known
correct answer" requirement) — all four in one judge call per question to
keep evaluation API cost down.
"""

from google import genai
from google.genai import types
from pydantic import BaseModel

DEFAULT_JUDGE_MODEL = "gemini-2.5-flash"


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

reasoning: one or two sentences justifying the scores.

Return only the JSON object matching the schema."""


def judge_answer(
    question: str,
    answer: str,
    reference_answer: str,
    context_chunks: list[str],
    *,
    client: genai.Client,
    model_name: str = DEFAULT_JUDGE_MODEL,
) -> AnswerJudgment:
    response = client.models.generate_content(
        model=model_name,
        contents=build_judge_prompt(question, answer, reference_answer, context_chunks),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AnswerJudgment,
            temperature=0.0,
        ),
    )
    return AnswerJudgment.model_validate_json(response.text)
