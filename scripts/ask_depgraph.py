"""Ask DepGraph a question: route it, retrieve, and synthesize a cited answer (Phases 7-9).

Prints the answer, then the evidence behind it: dependency chains, the
advisories with their osv.dev links, and the advisory text that was used.
Any advisory id in the answer that isn't in the evidence, or any citation
marker pointing at nothing, is flagged. --json prints everything.

Usage:
    uv run python scripts/ask_depgraph.py "Is axios@0.21.1 exposed to CVE-2022-0155?" [--json]
    uv run python scripts/ask_depgraph.py "How do I fix CVE-2022-0155 in axios@0.21.1?"
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from entitygraph_rag.depgraph import load_context, route_query
from entitygraph_rag.depgraph.synthesis import synthesize_answer
from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.llm_client import build_client
from entitygraph_rag.npm.advisory_index import DEFAULT_VARIANT, VARIANTS
from entitygraph_rag.retrieval import build_embedding_client

ROOT = Path(__file__).resolve().parent.parent
SHOW = 8


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default=DEFAULT_VARIANT)
    args = parser.parse_args()

    client = build_client()
    ctx = load_context(ROOT / "data" / "processed" / "depgraph", build_embedding_client(), args.variant)
    result = route_query(args.question, client=client, ctx=ctx, schema=load_schema(ROOT / "schema" / "v2.yaml"))
    answer = synthesize_answer(result, client=client)
    if args.json:
        print(json.dumps(answer, indent=2, default=str))
        return

    print(answer["answer"])
    print(f"\n--- route: {answer['route']}"
          + (f" (ran {answer['executed_route']})" if answer["executed_route"] != answer["route"] else ""))
    for w in answer["warnings"]:
        print(f"! {w}")
    checks = answer["checks"]
    if checks["ungrounded_ids"] or checks["unknown_markers"] or checks["ungrounded_versions"]:
        print(f"! ungrounded ids: {checks['ungrounded_ids']}  unknown markers: {checks['unknown_markers']}"
              f"  ungrounded versions: {checks['ungrounded_versions']}")
    cites = answer["citations"]
    if cites["dependency_chains"]:
        print(f"\nDependency chains ({len(cites['dependency_chains'])}):")
        for c in cites["dependency_chains"][:SHOW]:
            print(f"  {c}")
    if cites["advisories"]:
        print(f"\nAdvisories ({len(cites['advisories'])}):")
        for a in cites["advisories"][:SHOW]:
            print(f"  {a['id']} ({a['severity'] or 'unlabeled'}) {a['url']}")
    if cites["chunks"]:
        print("\nAdvisory text used:")
        for c in cites["chunks"]:
            print(f"  [{c['marker']}] {c['chunk_id']}  {c['url']}")


if __name__ == "__main__":
    main()
