"""Canonical Company registry built from config/companies.yaml.

The fixed 20-company universe is a strong resolution prior for the
dominant node type: an exact ticker or normalized-name match (or a
fuzzy match, or one of the small set of informal names/acronyms that
don't reduce to their legal name via suffix-stripping alone) resolves the
common case cheaply and reliably. Anything that doesn't match falls
through to generic fuzzy clustering (see cluster.py) — most often a
company mentioned only in passing that isn't part of our curated universe
(e.g. "Hugging Face").
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from .normalize import normalize_name

DEFAULT_COMPANIES_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "companies.yaml"

# Informal names/acronyms that come up in filing/transcript prose but don't
# reduce to their legal name via suffix-stripping alone. Curated once for
# this fixed 20-company universe rather than solved generally.
EXTRA_ALIASES: dict[str, str] = {
    "tsmc": "TSM",
    "google": "GOOGL",
    "stmicro": "STM",
    "st microelectronics": "STM",
}

FUZZY_MATCH_THRESHOLD = 88


@dataclass
class CompanyRecord:
    name: str
    ticker: str
    sector: str
    filer_type: str


class CompanyRegistry:
    def __init__(self, companies: list[CompanyRecord]):
        self.companies = companies
        self._by_ticker = {c.ticker.upper(): c for c in companies}
        self._by_normalized_name = {normalize_name(c.name): c for c in companies}

    def match(self, candidate_name: str) -> CompanyRecord | None:
        """Return the CompanyRecord this candidate resolves to, or None if outside the universe."""
        upper = candidate_name.strip().upper()
        if upper in self._by_ticker:
            return self._by_ticker[upper]

        normalized = normalize_name(candidate_name)
        alias_ticker = EXTRA_ALIASES.get(normalized)
        if alias_ticker is not None:
            return self._by_ticker[alias_ticker]
        if normalized in self._by_normalized_name:
            return self._by_normalized_name[normalized]

        best = process.extractOne(normalized, self._by_normalized_name.keys(), scorer=fuzz.token_sort_ratio)
        if best is not None and best[1] >= FUZZY_MATCH_THRESHOLD:
            return self._by_normalized_name[best[0]]
        return None


def load_company_registry(path: Path = DEFAULT_COMPANIES_PATH) -> CompanyRegistry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["companies"]
    records = [
        CompanyRecord(name=c["name"], ticker=c["ticker"], sector=c["sector"], filer_type=c["filer_type"])
        for c in raw
    ]
    return CompanyRegistry(records)
