"""Turn earnings-call transcript turns into Sections.

Transcripts arrive already speaker-segmented (`structured_content` is a list
of {"speaker", "text"} dicts), so no boundary detection is needed here —
each turn becomes its own Section, in order.
"""

from .schema import Section


def build_turn_sections(structured_content: list[dict]) -> list[Section]:
    sections = []
    for ordinal, turn in enumerate(structured_content):
        speaker = turn.get("speaker", "Unknown")
        text = turn.get("text", "")
        sections.append(Section(label=speaker, ordinal=ordinal, lines=[text]))
    return sections
