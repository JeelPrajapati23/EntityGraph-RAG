"""Word-count based, paragraph/sentence-aware chunk packing.

Chunk sizing is a simple word-count heuristic rather than a tokenizer count,
since the embedding model this feeds isn't chosen yet — swapping in a real
tokenizer later doesn't require touching the packing logic, only the word
count computed per unit.
"""

import re

from .schema import MAX_CHUNK_WORDS

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text) if s]


def pack_units(units: list[str], max_words: int = MAX_CHUNK_WORDS) -> list[str]:
    """Pack units (paragraphs or sentences) into chunks up to max_words.

    A single unit longer than max_words on its own becomes its own
    standalone chunk rather than being split mid-sentence or truncated.
    """
    chunks = []
    buffer: list[str] = []
    buffer_words = 0

    def flush() -> None:
        nonlocal buffer, buffer_words
        if buffer:
            chunks.append(" ".join(buffer))
            buffer = []
            buffer_words = 0

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        unit_words = len(unit.split())

        if buffer and buffer_words + unit_words > max_words:
            flush()

        buffer.append(unit)
        buffer_words += unit_words

        if unit_words > max_words:
            flush()

    flush()
    return chunks
