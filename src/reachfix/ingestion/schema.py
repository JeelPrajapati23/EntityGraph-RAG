"""Chunk record schema — the unit of output for the ingestion pipeline.

Every chunk carries full provenance back to its source document (`doc_id`,
`source_url`, `date`) and its position within it (`section_ordinal`,
`chunk_index`), matching the `edge_properties` provenance fields expected by
`schema/v1.yaml` for the extraction phase downstream.
"""

from dataclasses import dataclass

MAX_CHUNK_WORDS = 450


@dataclass
class Section:
    """A logical unit of a document (a filing Item, or a transcript turn)."""

    label: str
    ordinal: int
    lines: list[str]
    item_key: str | None = None


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    ticker: str
    doc_type: str  # "filing" | "transcript"
    form: str
    date: str
    source_url: str
    section: str
    section_ordinal: int
    chunk_index: int
    word_count: int
    text: str


def make_chunk_id(doc_id: str, section_ordinal: int, chunk_index: int) -> str:
    return f"{doc_id}::{section_ordinal}::{chunk_index}"
