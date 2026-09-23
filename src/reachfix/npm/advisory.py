"""Chunk OSV advisory `details` text for Phase 3's EXPLOITABLE_WHEN extraction.

`details` is markdown, usually GHSA's "### Impact / ### Patches /
### Workarounds" layout, sometimes with long PoC code blocks. It is split
into paragraphs at blank lines (never inside a fenced code block) and the
paragraphs are packed into chunks of at most MAX_CHUNK_WORDS words. Most
advisories fit in one chunk. Packing runs across headings, because
splitting at every heading would make two-line "Patches" sections into
chunks of their own. A heading stays in the text, glued to the paragraph
after it, so it never ends a chunk on its own.

Malicious-package (MAL-) records are skipped: their `details` is templated
incident boilerplate, not a description of when a flaw is exploitable.
"""

import re
from dataclasses import dataclass

MAX_CHUNK_WORDS = 450

OSV_WEB = "https://osv.dev/vulnerability/"
MALICIOUS_PREFIX = "MAL-"

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")


@dataclass
class AdvisoryChunk:
    chunk_id: str
    doc_id: str                  # OSV id, e.g. GHSA-74fj-2j2h-c42q
    source_url: str
    aliases: list[str]           # e.g. CVE ids
    summary: str
    severity: str | None         # GHSA label
    modified: str
    affected_packages: list[str]
    sections: list[str]          # markdown headings whose text is in this chunk ("" = before the first heading)
    chunk_index: int
    word_count: int
    text: str


def is_malicious(record: dict) -> bool:
    return record["id"].startswith(MALICIOUS_PREFIX)


def markdown_sections(text: str) -> list[tuple[str, list[str]]]:
    """(heading, paragraphs) in document order. Fenced code blocks stay whole."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    paragraph: list[str] = []
    in_fence = False

    def end_paragraph() -> None:
        if paragraph:
            sections[-1][1].append("\n".join(paragraph).strip())
            paragraph.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            paragraph.append(line)
            continue
        if in_fence:
            paragraph.append(line)
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            end_paragraph()
            sections.append((heading.group(1).strip(), []))
        elif not line.strip():
            end_paragraph()
        else:
            paragraph.append(line)
    end_paragraph()
    return [(h, [p for p in paras if p]) for h, paras in sections if any(paras)]


def advisory_units(sections: list[tuple[str, list[str]]]) -> list[tuple[str, str]]:
    """(heading, unit) pairs, with each heading glued to its section's first paragraph."""
    units = []
    for heading, paragraphs in sections:
        for i, para in enumerate(paragraphs):
            units.append((heading, f"### {heading}\n\n{para}" if heading and i == 0 else para))
    return units


def pack_advisory_units(units: list[tuple[str, str]], max_words: int) -> list[tuple[list[str], str]]:
    """Pack units into (headings, text) chunks of at most max_words.

    A unit longer than max_words (usually a PoC code block) becomes a chunk
    of its own instead of being cut.
    """
    chunks: list[tuple[list[str], str]] = []
    headings: list[str] = []
    texts: list[str] = []
    words = 0
    for heading, unit in units:
        unit_words = len(unit.split())
        if texts and words + unit_words > max_words:
            chunks.append((headings, "\n\n".join(texts)))
            headings, texts, words = [], [], 0
        if heading not in headings:
            headings.append(heading)
        texts.append(unit)
        words += unit_words
    if texts:
        chunks.append((headings, "\n\n".join(texts)))
    return chunks


def make_advisory_chunk_id(osv_id: str, chunk_index: int) -> str:
    return f"{osv_id}::{chunk_index}"


def chunk_advisory(record: dict, max_words: int = MAX_CHUNK_WORDS) -> list[AdvisoryChunk]:
    osv_id = record["id"]
    common = {
        "doc_id": osv_id,
        "source_url": OSV_WEB + osv_id,
        "aliases": record.get("aliases", []),
        "summary": record.get("summary", ""),
        "severity": record.get("database_specific", {}).get("severity"),
        "modified": record.get("modified", ""),
        "affected_packages": sorted({a["package"]["name"] for a in record.get("affected", []) if "package" in a}),
    }
    units = advisory_units(markdown_sections(record.get("details", "")))
    return [
        AdvisoryChunk(
            chunk_id=make_advisory_chunk_id(osv_id, index),
            sections=headings,
            chunk_index=index,
            word_count=len(text.split()),
            text=text,
            **common,
        )
        for index, (headings, text) in enumerate(pack_advisory_units(units, max_words))
    ]


def embedding_prefix(chunk: dict) -> str:
    """What every embedding window of an advisory chunk starts with: its summary and package names.

    31 of 383 chunks never name their own package in the text, so without
    this a "vulnerabilities in <package>" query can't find them.
    """
    packages = ", ".join(chunk.get("affected_packages", []))
    return f"{chunk.get('summary', '')}\nPackages: {packages}" if packages else chunk.get("summary", "")
