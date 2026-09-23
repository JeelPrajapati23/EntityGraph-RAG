"""Normalize entity name strings before matching for resolution.

Strips common corporate suffixes (including multi-word ones like "N.V.")
and casing/punctuation differences so "NVIDIA Corporation" and "nvidia"
normalize to the same key. Suffix-stripping mainly helps Company entities,
but applying the same normalization to every type is harmless — Person/
Product/Location names rarely carry these suffixes.
"""

import re

_MULTI_WORD_SUFFIXES = [r"n\.v\.", r"s\.a\."]
# (?<!\w)/(?!\w) rather than \b: \b requires a word/non-word transition, but
# both characters around a trailing "." here are non-word (the "." itself
# and the following space/end-of-string), so \b would never match there.
_MULTI_WORD_SUFFIX_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(_MULTI_WORD_SUFFIXES) + r")(?!\w)", re.IGNORECASE
)

_SUFFIX_WORDS = {
    "incorporated", "corporation", "corp", "inc", "co", "company",
    "ltd", "limited", "llc", "plc", "holding", "holdings", "group",
}


def normalize_name(name: str) -> str:
    text = _MULTI_WORD_SUFFIX_RE.sub(" ", name)
    text = re.sub(r"[.,]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()

    words = [w for w in text.split(" ") if w and w not in _SUFFIX_WORDS]
    return " ".join(words) if words else text
