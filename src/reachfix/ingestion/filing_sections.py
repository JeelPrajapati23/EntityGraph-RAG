"""Detect 10-K/10-Q/8-K "Item" section boundaries in cleaned filing text.

EDGAR filings' tables of contents repeat every Item heading verbatim before
the real body section, so a naive "line starts with Item N" scan produces
duplicate, wrongly-positioned boundaries. The fix: key each candidate by
(item_key, title) and keep only the last occurrence in document order — the
TOC always comes before the real body.

20-F is dispatched through this same path (SEC's General Instructions for
Form 20-F use the same "Item N[.letter]" numbering as 10-K), but this is
unverified against a real 20-F sample — none of the foreign private issuers
in config/companies.yaml (TSM, ASML, STM) have been downloaded yet.
TODO: verify once a real 20-F is downloaded.

6-K is a free-form "furnished" cover form with no standardized Item scheme,
so it deliberately skips this path entirely (see dispatch in pipeline.py).
"""

import re

from .schema import Section

ITEM_LINE_RE = re.compile(
    r"^item\s+(\d{1,2})(?:\.(\d{1,2}))?\s*([a-z])?\.?\s*(.*)$", re.IGNORECASE
)

_TITLE_LOOKAHEAD = 3
_TITLE_PREFIX_WORDS = 8


def _item_key(major: str, minor: str | None, letter: str | None) -> str:
    if minor:
        return f"{major}.{minor}"
    if letter:
        return f"{major}{letter.upper()}"
    return major


def detect_item_boundaries(lines: list[str]) -> list[Section]:
    """Split cleaned lines into Item sections, or one FULL_DOCUMENT fallback."""
    candidates: dict[tuple[str, str], tuple[int, str, str]] = {}

    for idx, line in enumerate(lines):
        match = ITEM_LINE_RE.match(line)
        if not match:
            continue
        major, minor, letter, inline_title = match.groups()
        item_key = _item_key(major, minor, letter)

        title = inline_title.strip()
        if not title:
            for lookahead_idx in range(idx + 1, min(idx + 1 + _TITLE_LOOKAHEAD, len(lines))):
                candidate = lines[lookahead_idx].strip()
                if candidate:
                    title = candidate
                    break

        # Word-only (punctuation-stripped) so a TOC entry using a curly
        # apostrophe ("Registrant’s") still dedupes against the real
        # header using a straight one ("Registrant's") - confirmed this
        # happens in real EDGAR filings (10-K Items 5 and 7).
        title_prefix = " ".join(re.findall(r"\w+", title.lower())[:_TITLE_PREFIX_WORDS])
        key = (item_key, title_prefix)
        candidates[key] = (idx, item_key, title)

    if not candidates:
        return [Section(label="FULL_DOCUMENT", ordinal=0, lines=list(lines), item_key=None)]

    boundaries = sorted(candidates.values(), key=lambda entry: entry[0])

    sections = []
    for ordinal, (start_idx, item_key, title) in enumerate(boundaries):
        end_idx = boundaries[ordinal + 1][0] if ordinal + 1 < len(boundaries) else len(lines)
        # Body starts after the Item line itself (and its title line, if the
        # title wasn't inline — harmless to include the title line if it was
        # inline, since it's already part of the Item line's own text).
        body_start = start_idx + 1
        body_lines = [line for line in lines[body_start:end_idx] if line != title]
        label = f"Item {item_key} — {title}" if title else f"Item {item_key}"
        sections.append(Section(label=label, ordinal=ordinal, lines=body_lines, item_key=item_key))

    return sections
