"""Split a registry license string into License node ids.

Registry license strings are mostly SPDX ids ("MIT") or simple SPDX
expressions ("(MIT OR CC0-1.0)"). A few legacy spellings get mapped to
their SPDX id. Anything else (e.g. "BSD", which names no single SPDX
license) is kept verbatim rather than guessed.
"""

import re
from dataclasses import dataclass

LEGACY_SPELLINGS = {
    "Apache 2.0": "Apache-2.0",
    "AFLv2.1": "AFL-2.1",
}
_OPERATOR_RE = re.compile(r"\s+(OR|AND)\s+")


@dataclass(frozen=True)
class LicenseExpression:
    expression: str        # normalized, e.g. "MIT OR CC0-1.0"
    ids: tuple[str, ...]   # component licenses, e.g. ("MIT", "CC0-1.0")
    operator: str | None   # "OR" (choose one), "AND" (all apply), or None for a single license


def parse_license(raw: str | None) -> LicenseExpression | None:
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    parts = _OPERATOR_RE.split(text)
    ids = tuple(LEGACY_SPELLINGS.get(p.strip(), p.strip()) for p in parts[::2])
    operators = set(parts[1::2])
    if len(operators) > 1 or any("(" in i or ")" in i for i in ids):
        # Mixed or nested expression: keep it whole instead of misreading it.
        return LicenseExpression(expression=raw.strip(), ids=(raw.strip(),), operator=None)
    operator = operators.pop() if operators else None
    expression = f" {operator} ".join(ids) if operator else ids[0]
    return LicenseExpression(expression=expression, ids=ids, operator=operator)
