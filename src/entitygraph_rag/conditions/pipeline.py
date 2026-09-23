"""Extract EXPLOITABLE_WHEN edges from one advisory chunk, with caching and an evidence check.

Each returned item goes through two gates before becoming an edge:
1. it parses against the schema-generated output model (unknown relation or
   category, missing field, confidence out of range), and
2. its `evidence` quote is found in the chunk text or advisory summary,
   ignoring case, whitespace and markdown punctuation. A quote of
   FUZZY_MIN_WORDS or more words may instead match at FUZZY_MIN_SCORE or
   above, which tolerates a dropped "the". Short quotes must match exactly,
   since a fuzzy match on a few words means little. This is what makes the
   LLM's output falsifiable: every edge points at the words it came from,
   and records whether the match was exact.

Malformed output drops the whole chunk (not cached, so a re-run retries it).
An item failing the evidence check is dropped on its own, with a warning.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from groq import Groq
from pydantic import BaseModel, TypeAdapter, ValidationError
from rapidfuzz import fuzz

from ..extraction import cache
from ..extraction.schema import Schema
from ..llm_client import generate_json
from .prompt import build_user_prompt

_MARKDOWN_NOISE_RE = re.compile(r"[`*_\[\]]")
_WHITESPACE_RE = re.compile(r"\s+")
FUZZY_MIN_WORDS = 6
FUZZY_MIN_SCORE = 95


def normalize_for_match(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", _MARKDOWN_NOISE_RE.sub("", text)).strip().lower()


def evidence_match(evidence: str, chunk: dict) -> str | None:
    """"exact", "fuzzy", or None if the quote isn't in the chunk text or summary."""
    needle = normalize_for_match(evidence)
    haystack = normalize_for_match(chunk["text"] + "\n" + chunk.get("summary", ""))
    if not needle:
        return None
    if needle in haystack:
        return "exact"
    if len(needle.split()) >= FUZZY_MIN_WORDS and fuzz.partial_ratio(needle, haystack) >= FUZZY_MIN_SCORE:
        return "fuzzy"
    return None


def parse_extractions(raw_json: str, model: type[BaseModel]) -> list[BaseModel]:
    data = json.loads(raw_json)
    items = data["extractions"] if isinstance(data, dict) else data
    return TypeAdapter(list[model]).validate_python(items)


def extract_conditions(
    chunk: dict,
    *,
    schema: Schema,
    model: type[BaseModel],
    client: Groq,
    model_name: str,
    system_prompt: str,
    cache_root: Path,
) -> tuple[list[dict], list[str]]:
    """Return (edges, warnings) for one chunk, using the cache when possible."""
    user_prompt = build_user_prompt(chunk)
    # The prompts are part of the key, so a prompt or schema edit invalidates the cache.
    key = cache.make_cache_key(
        chunk["chunk_id"], system_prompt + "\n" + user_prompt, model_name=model_name, schema_version=schema.version
    )
    cached = cache.read_cache(cache_root, key)
    if cached is not None:
        return cached, []

    raw_json = generate_json(client, system_prompt=system_prompt, user_prompt=user_prompt, model_name=model_name)
    try:
        items = parse_extractions(raw_json, model)
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        return [], [f"{chunk['chunk_id']}: LLM output failed to parse ({exc.__class__.__name__}: {exc})"]

    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    edges, warnings = [], []
    for item in items:
        match = evidence_match(item.evidence, chunk)
        if match is None:
            warnings.append(f"{chunk['chunk_id']}: dropped {item.text!r} (evidence not in text: {item.evidence!r})")
            continue
        fields = item.model_dump()
        relation = fields.pop("relation")
        edges.append({
            "relation": relation,
            "extraction_method": "llm",
            "subject": chunk["doc_id"],
            "condition_id": f"{chunk['chunk_id']}::{len(edges)}",
            **fields,
            "evidence_match": match,
            "source_chunk_id": chunk["chunk_id"],
            "source_doc_id": chunk["doc_id"],
            "source_url": chunk["source_url"],
            "model": model_name,
            "extracted_at": extracted_at,
        })

    cache.write_cache(cache_root, key, edges)
    return edges, warnings
