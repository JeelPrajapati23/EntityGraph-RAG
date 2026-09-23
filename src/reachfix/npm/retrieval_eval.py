"""Label-free checks for advisory retrieval, using facts already in the data.

There are no hand-labeled relevance judgments yet, so two proxy query sets
are used:

- Package queries: "what security vulnerabilities has <pkg> had?" for every
  package named by at least MIN_ADVISORIES advisories. A retrieved chunk is
  relevant if its advisory's `affected_packages` includes the package
  (OSV's structured field, not text).
- Class queries: paraphrased descriptions of a vulnerability class. A
  retrieved chunk is relevant if its advisory's summary or details match
  the class pattern. The queries deliberately avoid the pattern's words, so
  a hit needs a semantic match, not a lexical one.

Both report precision@k over distinct advisories.
"""

import re
from collections import Counter, defaultdict

MIN_ADVISORIES = 3
PACKAGE_QUERY = "what security vulnerabilities has {package} had?"

CLASS_QUERIES = [
    ("slow regex that burns CPU on a crafted input string",
     r"regular expression denial|redos|catastrophic backtracking|inefficient regular expression"),
    ("attacker adds properties to every object through crafted keys like __proto__",
     r"prototype pollution"),
    ("reading files outside the directory the server is supposed to serve",
     r"path traversal|directory traversal|\.\./"),
    ("injecting script into a page through unsanitized markup",
     r"cross-site scripting|xss"),
    ("a server tricked into fetching internal URLs chosen by the attacker",
     r"server-side request forgery|ssrf"),
    ("credentials or cookies sent to another host after following a redirect",
     r"redirect"),
    ("attacker runs arbitrary shell commands on the host",
     r"command injection|remote code execution|arbitrary code|code injection|arbitrary command"),
    ("crashing the process with a huge input that exhausts memory",
     r"memory exhaustion|out[- ]of[- ]memory|resource exhaustion|uncontrolled resource consumption|memory consumption"),
]


def advisory_text(chunks: list[dict]) -> dict[str, str]:
    """doc_id -> summary + every chunk's text, lower-cased, for pattern relevance."""
    parts: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        if not parts[chunk["doc_id"]]:
            parts[chunk["doc_id"]].append(chunk.get("summary", ""))
        parts[chunk["doc_id"]].append(chunk["text"])
    return {doc_id: "\n".join(texts).lower() for doc_id, texts in parts.items()}


def package_queries(chunks: list[dict]) -> list[tuple[str, str]]:
    """(query, package) for every package named by at least MIN_ADVISORIES advisories."""
    advisories: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        for package in chunk.get("affected_packages", []):
            advisories[package].add(chunk["doc_id"])
    return [(PACKAGE_QUERY.format(package=p), p) for p in sorted(advisories) if len(advisories[p]) >= MIN_ADVISORIES]


def distinct_advisories(results: list[dict], k: int) -> list[dict]:
    """The first k results from distinct advisories (several chunks can share one)."""
    seen, out = set(), []
    for r in results:
        if r["doc_id"] not in seen:
            seen.add(r["doc_id"])
            out.append(r)
        if len(out) == k:
            break
    return out


def precision(results: list[dict], relevant) -> float:
    return sum(relevant(r) for r in results) / len(results) if results else 0.0


def summarize(scores: list[float]) -> dict:
    return {"queries": len(scores), "mean_precision": round(sum(scores) / len(scores), 3) if scores else None,
            "all_relevant": sum(s == 1.0 for s in scores), "none_relevant": sum(s == 0.0 for s in scores)}


def class_relevance(pattern: str, texts: dict[str, str]):
    regex = re.compile(pattern, re.IGNORECASE)
    return lambda result: bool(regex.search(texts.get(result["doc_id"], "")))


def class_base_rate(pattern: str, texts: dict[str, str]) -> float:
    """Share of all advisories matching the pattern: what random retrieval would score."""
    regex = re.compile(pattern, re.IGNORECASE)
    return sum(bool(regex.search(t)) for t in texts.values()) / len(texts)


def package_counts(chunks: list[dict]) -> Counter:
    return Counter(p for c in chunks for p in c.get("affected_packages", []))
