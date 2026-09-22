"""Thin Groq wrapper for chat/JSON completions (openai/gpt-oss-120b by default).

Shared by every generation call site — extraction, router classification,
answer synthesis, and eval judging — the way extraction/gemini_client.py
used to be before the Groq migration. Groq's OpenAI-compatible API doesn't
offer Gemini's response_schema-level validation, so generate_json only
guarantees syntactically valid JSON (via response_format json_object);
callers still validate the returned text against their own Pydantic model
(see extraction/schema.py's validate_triple, router/classify.py's
RouterDecision, evaluation/judge.py's AnswerJudgment).
"""

import os

from groq import Groq

DEFAULT_MODEL = "openai/gpt-oss-120b"


def build_client(api_key: str | None = None) -> Groq:
    api_key = api_key or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set (check .env)")
    return Groq(api_key=api_key)


def _messages(system_prompt: str | None, user_prompt: str) -> list[dict]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def generate_text(
    client: Groq,
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = 0.0,
) -> str:
    response = client.chat.completions.create(
        model=model_name, messages=_messages(system_prompt, user_prompt), temperature=temperature,
    )
    return response.choices[0].message.content


def generate_json(
    client: Groq,
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = 0.0,
) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=_messages(system_prompt, user_prompt),
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content
