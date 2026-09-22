"""Orchestrate manifest row -> raw document -> Sections -> Chunk records.

Filing forms with no standardized numbered-Item structure (6-K) skip
Item-boundary detection entirely and are treated as one FULL_DOCUMENT
section, same as a filing where detection finds nothing.
"""

import json
from pathlib import Path

from .chunker import pack_units, split_sentences
from .filing_sections import detect_item_boundaries
from .html_clean import clean_filing_html
from .schema import MAX_CHUNK_WORDS, Chunk, Section, make_chunk_id
from .transcript_sections import build_turn_sections

NO_ITEM_STRUCTURE_FORMS = {"6-K"}


def load_manifest(path: Path) -> list[dict] | None:
    """Return parsed manifest rows, or None if the manifest file is missing."""
    if not path.exists():
        return None
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def process_filing(record: dict, root: Path) -> list[Chunk]:
    form = record["form"]
    local_path = root / record["local_path"]
    html = local_path.read_text(encoding="utf-8", errors="ignore")
    lines = clean_filing_html(html)

    if form in NO_ITEM_STRUCTURE_FORMS:
        sections = [Section(label="FULL_DOCUMENT", ordinal=0, lines=lines, item_key=None)]
    else:
        sections = detect_item_boundaries(lines)

    return _sections_to_chunks(
        sections,
        doc_id=record["doc_id"],
        ticker=record["ticker"],
        doc_type="filing",
        form=form,
        date=record["filing_date"],
        source_url=record["source_url"],
        use_sentence_split=False,
    )


def process_transcript(record: dict, root: Path) -> list[Chunk]:
    local_path = root / record["local_path"]
    data = json.loads(local_path.read_text(encoding="utf-8"))
    sections = build_turn_sections(data["structured_content"])

    return _sections_to_chunks(
        sections,
        doc_id=record["doc_id"],
        ticker=record["ticker"],
        doc_type="transcript",
        form="transcript",
        date=record["filing_date"],
        source_url=record["source"],
        use_sentence_split=True,
    )


def _sections_to_chunks(
    sections: list[Section],
    *,
    doc_id: str,
    ticker: str,
    doc_type: str,
    form: str,
    date: str,
    source_url: str,
    use_sentence_split: bool,
) -> list[Chunk]:
    chunks = []
    for section in sections:
        units = section.lines
        if use_sentence_split and len(units) == 1 and len(units[0].split()) > MAX_CHUNK_WORDS:
            units = split_sentences(units[0])

        for chunk_index, text in enumerate(pack_units(units)):
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(doc_id, section.ordinal, chunk_index),
                    doc_id=doc_id,
                    ticker=ticker,
                    doc_type=doc_type,
                    form=form,
                    date=date,
                    source_url=source_url,
                    section=section.label,
                    section_ordinal=section.ordinal,
                    chunk_index=chunk_index,
                    word_count=len(text.split()),
                    text=text,
                )
            )
    return chunks
