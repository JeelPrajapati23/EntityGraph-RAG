"""Thin Gemini wrapper for structured triple extraction.

The network call (call_gemini) and the parsing of its JSON output
(parse_triples) are kept separate so parsing — where extraction bugs
actually tend to live — is unit-testable without hitting the API.
"""

import os

from google import genai
from google.genai import types
from pydantic import BaseModel, TypeAdapter

DEFAULT_MODEL = "gemini-2.5-flash"


def build_client(api_key: str | None = None) -> genai.Client:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set (check .env)")
    return genai.Client(api_key=api_key)


def call_gemini(
    client: genai.Client,
    *,
    system_prompt: str,
    user_prompt: str,
    triple_model: type[BaseModel],
    model_name: str = DEFAULT_MODEL,
) -> str:
    """Call Gemini with structured-output config and return the raw JSON response text."""
    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=list[triple_model],
            temperature=0.0,
        ),
    )
    return response.text


def parse_triples(raw_json: str, triple_model: type[BaseModel]) -> list[BaseModel]:
    """Parse and validate a JSON triples response against triple_model.

    Raises pydantic.ValidationError on malformed output (unknown relation,
    missing field, etc.) rather than silently coercing — callers decide
    whether to skip, retry, or fail the chunk.
    """
    return TypeAdapter(list[triple_model]).validate_json(raw_json)
