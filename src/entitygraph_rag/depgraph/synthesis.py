"""Turn a DepGraph router result into a cited answer (Phase 8).

Three things are kept apart, as in the finance synthesis:
- Evidence for the model: numbered graph facts [G1..] (readable dependency
  chains, relations) and advisory chunks [A1..] with their full text.
- Exact totals, never computed by the model. react-scripts alone has 177
  advisories in its tree, so the model gets the counts (from the router,
  over every row, before its cap) plus a capped list ranked worst severity
  first, instead of hundreds of rows to count.
- The citation block returned to the caller: every chain, every advisory
  with its osv.dev URL, and chunk previews. Previews are for display only;
  the model reasoned over the full text.

After generation, the answer is checked: citation markers must point at
evidence that exists, and every CVE / GHSA / MAL id in the answer must
appear in the evidence. An id that doesn't is flagged as ungrounded.
"""

import re

from groq import Groq

from ..llm_client import DEFAULT_MODEL, generate_text

MAX_GRAPH_FACTS = 40
SNIPPET_CHARS = 300
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
# The model sometimes writes ids with Unicode hyphens (U+2010-2012, e.g. a
# non-breaking hyphen inside "GHSA-33f9-...") and citations in full-width
# brackets (U+3010/3011), and slips zero-width spaces into markers. These break
# copy-paste, search, and the checks below, so they are normalized to "-" and
# "[ ]" and the zero-width spaces dropped. Dashes are left alone.
ANSWER_NORMALIZATION = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u3010": "[", "\u3011": "]", "\u200b": None})
ADVISORY_ID_RE = re.compile(r"\b(CVE-\d{4}-\d{4,}|GHSA(?:-[0-9a-z]{4}){3}|MAL-\d{4}-\d+)\b", re.IGNORECASE)
# "jws @3.2.2" / "jws @ 3.2.2" -> "jws@3.2.2": the model sometimes spaces out package@version.
SPACED_VERSION_RE = re.compile(r"(?<=[\w.-]) ?@ ?(?=\d)")
MARKER_GROUP_RE = re.compile(r"\[([^\]]+)\]")
MARKER_RE = re.compile(r"\b([GA]\d+)\b")

SYSTEM_PROMPT = """You answer questions about npm dependency trees and security \
advisories using ONLY the evidence given: graph facts [G#], exact totals, and \
advisory text [A#]. Do not use outside knowledge.

- Cite every claim with the markers it rests on, e.g. [G2] or [A1].
- When you name a vulnerability, give its advisory id and CVE as written in \
the evidence. Never mention an id that is not in the evidence.
- When a dependency chain answers the question, quote it exactly as given.
- Use the exact totals as given; don't recount the listed facts, which may \
be a capped subset.
- If the evidence lists no vulnerability for something, say none is known in \
this dataset, not that it is safe.
- If the evidence doesn't answer the question, say so plainly.
- Be concise: a short direct answer first, then the supporting details. List \
at most 10 advisories or paths (the most severe first) and summarize the rest \
with the exact totals."""


def short(node_id: str) -> str:
    return node_id.removeprefix("npm:")


def advisory_label(row: dict) -> str:
    cves = [a for a in row.get("aliases", []) if a.upper().startswith("CVE-")]
    return " / ".join([row["vulnerability_id"], *cves])


def vuln_tag(row: dict) -> str:
    severity = f", {row['severity']}" if row.get("severity") else ""
    return f"[VULNERABLE: {advisory_label(row)}{severity}]"


def chain(path: list[str]) -> str:
    """The plan's readable form: a → depends_on → b → depends_on → c."""
    return " → depends_on → ".join(short(n) for n in path)


def _rank(row: dict) -> tuple:
    return (SEVERITY_ORDER.get(row.get("severity"), 4), row.get("depth", 0), row["vulnerability_id"])


def _exposure_facts(result: dict) -> tuple[list[str], list[str], list[dict], list[str]]:
    """(facts, totals, advisories, chains) for exposure / affected_projects rows."""
    rows = result.get("results", [])
    # One row per (project, advisory, version); the same finding can arrive once per lockfile.
    best: dict[tuple, dict] = {}
    for row in rows:
        best.setdefault((row["project"], row["vulnerability_id"], row["version_id"]), row)
    ranked = sorted(best.values(), key=_rank)

    facts, chains = [], []
    for row in ranked:
        fix = f" Fixed in: {', '.join(short(v) for v in row['fixed_in'])}." if row.get("fixed_in") else " No fixed version listed."
        line = f"{chain(row['path'])} {vuln_tag(row)} {row.get('summary') or ''}.{fix}"
        chains.append(f"{chain(row['path'])} {vuln_tag(row)}")
        facts.append(line)

    totals = []
    for project, t in result.get("totals", {}).items():
        sev = ", ".join(f"{n} {s.lower()}" for s, n in t["by_severity"].items())
        totals.append(f"{short(project)}: {t['advisories']} advisories on {t['vulnerable_versions']} "
                      f"vulnerable versions ({sev}); deepest at {t['max_depth']} hops.")
    total_rows = result.get("total_results", len(rows))
    if not ranked:
        scope = ", ".join(short(p) for p in result.get("projects", [])) or "the named entities"
        totals.append(f"No known vulnerable dependency found for {scope} in this dataset.")
    if total_rows > len(rows):
        totals.append(f"Only the {len(rows)} most severe of {total_rows} (project, advisory, version) findings "
                      f"are listed as facts; the totals above cover all of them.")
    if len(facts) > MAX_GRAPH_FACTS:
        totals.append(f"Graph facts below show the {MAX_GRAPH_FACTS} most severe of {len(facts)}.")
    advisories = list({r["vulnerability_id"]: r for r in ranked}.values())
    return facts[:MAX_GRAPH_FACTS], totals, advisories, chains


def _path_facts(result: dict) -> tuple[list[str], list[str], list[dict], list[str]]:
    facts, chains, advisories = [], [], {}
    for row in result.get("results", []):
        tags = " ".join(vuln_tag(v) for v in row.get("vulnerabilities", []))
        chains.append(f"{chain(row['path'])} {tags}".strip())
        fixes = "; ".join(f"{v['vulnerability_id']} fixed in {', '.join(short(f) for f in v['fixed_in']) or 'no listed version'}"
                          for v in row.get("vulnerabilities", []))
        facts.append(f"{chains[-1]} ({row['depth']} hops).{(' ' + fixes + '.') if fixes else ''}")
        advisories.update({v["vulnerability_id"]: v for v in row.get("vulnerabilities", [])})
    totals = [f"{len(facts)} dependency paths found."] if facts else ["No dependency path found between them."]
    return facts[:MAX_GRAPH_FACTS], totals, list(advisories.values()), chains


def _neighbor_facts(result: dict) -> tuple[list[str], list[str], list[dict], list[str]]:
    labels = {a["vulnerability_id"]: advisory_label(a) for a in result.get("advisories", [])}
    facts = []
    for row in result.get("results", []):
        subj, obj = (row["source"]["name"], row["name"]) if row["direction"] == "out" else (row["name"], row["source"]["name"])
        line = f"{labels.get(subj, short(subj))} --{row['relation']}--> {labels.get(obj, short(obj))}"
        quotes = [p["evidence"] for p in row.get("provenance", []) if p.get("evidence")]
        if quotes:
            line += " (advisory text: " + " | ".join(f'"{q}"' for q in quotes) + ")"
        props = row.get("properties", {})
        if props.get("expression") and props.get("operator"):
            line += f" (license expression: {props['expression']})"
        facts.append(line)
    totals = [f"{len(facts)} relations found."] if facts else ["No such relation found in the graph."]
    return facts[:MAX_GRAPH_FACTS], totals, result.get("advisories", []), facts


def _hybrid_facts(result: dict) -> tuple[list[str], list[str], list[dict], list[str]]:
    advisories = result.get("advisories", [])
    ranked = sorted(advisories, key=lambda a: (SEVERITY_ORDER.get(a.get("severity"), 4), a["vulnerability_id"]))
    facts = [f"{advisory_label(a)} ({a.get('severity') or 'unlabeled'}): {a.get('summary') or ''}" for a in ranked]
    totals = [f"The named entities link to {len(advisories)} advisories in the graph; the text below comes only from them."]
    return facts[:MAX_GRAPH_FACTS], totals, ranked, []


def build_evidence(result: dict) -> dict:
    """Everything synthesis shows the model and returns as citations, from a router result."""
    route = result["executed_route"]
    if route == "relational":
        builder = {"exposure": _exposure_facts, "affected_projects": _exposure_facts,
                   "dependency_path": _path_facts}.get(result.get("executed_pattern") or result.get("pattern"), _neighbor_facts)
        facts, totals, advisories, chains = builder(result)
    elif route == "graph_guided_hybrid":
        facts, totals, advisories, chains = _hybrid_facts(result)
    else:
        facts, totals, advisories, chains = [], [], [], []
    chunks = result.get("chunks", [])
    return {"facts": facts, "totals": totals, "advisories": advisories, "chains": chains, "chunks": chunks}


def build_user_prompt(query: str, evidence: dict, warnings: list[str]) -> str:
    facts = "\n".join(f"[G{i}] {f}" for i, f in enumerate(evidence["facts"], 1)) or "(none)"
    totals = "\n".join(f"- {t}" for t in evidence["totals"]) or "(none)"
    chunks = "\n\n".join(
        f"[A{i}] {c['doc_id']} ({', '.join(c.get('affected_packages', []))}): {c.get('summary', '')}\n{c['text']}"
        for i, c in enumerate(evidence["chunks"], 1)) or "(none)"
    notes = "\n".join(f"- {w}" for w in warnings)
    return (f"Question: {query}\n\n"
            + (f"Retrieval notes:\n{notes}\n\n" if notes else "")
            + f"Exact totals:\n{totals}\n\nGraph facts:\n{facts}\n\nAdvisory text:\n{chunks}\n\nAnswer:")


def grounded_ids(evidence: dict) -> set[str]:
    ids = set()
    for a in evidence["advisories"]:
        ids.update([a["vulnerability_id"], *a.get("aliases", [])])
    for c in evidence["chunks"]:
        ids.update([c["doc_id"], *c.get("aliases", [])])
    for line in evidence["facts"]:
        ids.update(ADVISORY_ID_RE.findall(line))
    return {i.upper() for i in ids}


def check_answer(answer: str, evidence: dict) -> dict:
    """Citation markers that point at nothing, and advisory ids not in the evidence."""
    valid = {f"G{i}" for i in range(1, len(evidence["facts"]) + 1)} | {f"A{i}" for i in range(1, len(evidence["chunks"]) + 1)}
    markers = {m for group in MARKER_GROUP_RE.findall(answer) for m in MARKER_RE.findall(group)}
    mentioned = {m.upper() for m in ADVISORY_ID_RE.findall(answer)}
    return {
        "unknown_markers": sorted(markers - valid),
        "ungrounded_ids": sorted(mentioned - grounded_ids(evidence)),
        "cited_markers": sorted(markers & valid),
    }


def citation_block(evidence: dict) -> dict:
    return {
        "dependency_chains": evidence["chains"],
        "advisories": [{"id": a["vulnerability_id"], "aliases": a.get("aliases", []), "severity": a.get("severity"),
                        "summary": a.get("summary"), "url": a.get("source_url")} for a in evidence["advisories"]],
        "chunks": [{"marker": f"A{i}", "chunk_id": c["chunk_id"], "advisory": c["doc_id"], "url": c.get("source_url"),
                    "snippet": c["text"][:SNIPPET_CHARS]} for i, c in enumerate(evidence["chunks"], 1)],
        "graph_facts": [{"marker": f"G{i}", "fact": f} for i, f in enumerate(evidence["facts"], 1)],
    }


def synthesize_answer(result: dict, *, client: Groq, model_name: str = DEFAULT_MODEL) -> dict:
    evidence = build_evidence(result)
    prompt = build_user_prompt(result["query"], evidence, result.get("warnings", []))
    answer = generate_text(client, system_prompt=SYSTEM_PROMPT, user_prompt=prompt, model_name=model_name)
    answer = SPACED_VERSION_RE.sub("@", answer.translate(ANSWER_NORMALIZATION))
    return {
        "query": result["query"],
        "route": result["route"],
        "executed_route": result["executed_route"],
        "answer": answer,
        "checks": check_answer(answer, evidence),
        "totals": evidence["totals"],
        "citations": citation_block(evidence),
        "warnings": result.get("warnings", []),
    }
