"""Strip EDGAR filing HTML down to clean, line-per-paragraph text.

EDGAR HTML is heavily inline-styled (text like "Item 1A." is often split
across multiple <span> tags), so Item-boundary detection must run on cleaned
text, never on raw HTML.
"""

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

_PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")
_TOC_HEADER_RE = re.compile(r"^table of contents$", re.IGNORECASE)

# Some EDGAR filings carry an inline-XBRL/XML preamble even with a .htm
# extension; bs4 still parses them correctly as HTML, so this warning is
# expected noise here, not a sign of a bad parse.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def clean_filing_html(html: str) -> list[str]:
    """Return cleaned, noise-filtered lines (~one per paragraph)."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n")
    text = text.replace("\xa0", " ")

    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if _PAGE_NUMBER_RE.match(line) or _TOC_HEADER_RE.match(line):
            continue
        lines.append(line)
    return lines
