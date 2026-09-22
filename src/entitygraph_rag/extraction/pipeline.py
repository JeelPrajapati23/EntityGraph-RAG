"""Orchestrate schema-driven LLM extraction, with caching and post-hoc validation.

A chunk's triples go through three gates before becoming a graph edge:
parse against the Triple model (malformed LLM output), validate subject/
object type against the relation's schema entry (see schema.validate_triple
— structured-output APIs can't express that constraint at the field level),
then get enriched with edge_properties (source_chunk_id, source_doc_id,
confidence already present, extracted_at). A triple failing either gate is
dropped with a warning rather than failing the whole chunk.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from groq import Groq
from pydantic import BaseModel, TypeAdapter, ValidationError

from ..llm_client import generate_json
from . import cache
from .prompt import build_user_prompt
from .schema import Schema, validate_triple


def _parse_triples(raw_json: str, triple_model: type[BaseModel]) -> list[BaseModel]:
    """Parse and validate a {"triples": [...]} (or bare-list) JSON response against triple_model.

    Raises on malformed output (unknown relation, missing field, wrong
    shape) rather than silently coercing — callers decide whether to skip,
    retry, or fail the chunk.
    """
    data = json.loads(raw_json)
    triples_raw = data["triples"] if isinstance(data, dict) else data
    return TypeAdapter(list[triple_model]).validate_python(triples_raw)


def _to_edge(triple: BaseModel, *, chunk: dict, extracted_at: str) -> dict:
    return {
        "subject": triple.subject,
        "subject_type": triple.subject_type,
        "relation": triple.relation,
        "object": triple.object,
        "object_type": triple.object_type,
        "confidence": triple.confidence,
        "source_chunk_id": chunk["chunk_id"],
        "source_doc_id": chunk["doc_id"],
        "extracted_at": extracted_at,
    }


def extract_for_chunk(
    chunk: dict,
    *,
    schema: Schema,
    triple_model: type[BaseModel],
    client: Groq,
    model_name: str,
    system_prompt: str,
    cache_root: Path,
) -> tuple[list[dict], list[str]]:
    """Return (accepted edges, warnings) for one chunk, using the cache when possible."""
    key = cache.make_cache_key(
        chunk["chunk_id"], chunk["text"], model_name=model_name, schema_version=schema.version
    )
    cached = cache.read_cache(cache_root, key)
    if cached is not None:
        return cached, []

    warnings: list[str] = []
    try:
        raw_json = generate_json(
            client,
            system_prompt=system_prompt,
            user_prompt=build_user_prompt(chunk["text"]),
            model_name=model_name,
        )
        triples = _parse_triples(raw_json, triple_model)
    except (ValidationError, ValueError, KeyError) as exc:
        warnings.append(f"{chunk['chunk_id']}: LLM output failed to parse ({exc.__class__.__name__}: {exc})")
        return [], warnings

    extracted_at = datetime.now(timezone.utc).isoformat()
    edges = []
    for triple in triples:
        reason = validate_triple(schema, triple)
        if reason is not None:
            warnings.append(f"{chunk['chunk_id']}: dropped triple ({reason})")
            continue
        edges.append(_to_edge(triple, chunk=chunk, extracted_at=extracted_at))

    cache.write_cache(cache_root, key, edges)
    return edges, warnings
