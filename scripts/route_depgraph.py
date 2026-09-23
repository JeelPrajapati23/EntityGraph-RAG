"""Route one question through the DepGraph router and print what it retrieved.

Shows the route, pattern, how each named entity resolved, and the top
results: dependency paths for graph routes, advisory chunks for text
routes. No answer synthesis (that is Phase 8). --json prints the full result.

Usage:
    uv run python scripts/route_depgraph.py "Is axios@0.21.1 exposed to CVE-2022-0155?" [--json]
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from entitygraph_rag.depgraph import load_context, route_query
from entitygraph_rag.extraction.schema import load_schema
from entitygraph_rag.llm_client import build_client
from entitygraph_rag.npm.advisory_index import DEFAULT_VARIANT, VARIANTS
from entitygraph_rag.retrieval import build_embedding_client

ROOT = Path(__file__).resolve().parent.parent
SHOW = 10


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default=DEFAULT_VARIANT)
    args = parser.parse_args()

    ctx = load_context(ROOT / "data" / "processed" / "depgraph", build_embedding_client(), args.variant)
    result = route_query(args.question, client=build_client(), ctx=ctx, schema=load_schema(ROOT / "schema" / "v2.yaml"))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    print(f"route: {result['route']}" + (f" -> ran {result['executed_route']}" if result["executed_route"] != result["route"] else "")
          + (f" / {result['pattern']}" if result["pattern"] else "") + (f" / {result['relation']}" if result["relation"] else ""))
    print(f"why:   {result['classification_reasoning']}")
    for e in result["entities"]:
        print(f"  {e['name']!r} -> {', '.join(e['node_ids'])}")
    for w in result["warnings"]:
        print(f"  ! {w}")

    rows = result.get("results", [])
    if rows:
        print(f"\n{result.get('total_results', len(rows))} results (showing {min(SHOW, len(rows))}):")
    for row in rows[:SHOW]:
        if "path" in row:
            tail = f"  [{row['vulnerability_id']} {row.get('severity') or ''}]" if "vulnerability_id" in row else ""
            print("  " + " -> ".join(row["path"]) + tail)
        else:
            print(f"  {row['source']['name']} --{row['relation']}--> {row['name']}")
    if result.get("advisories"):
        print(f"\ngraph scoped the search to {len(result['advisories'])} advisories")
    for chunk in result.get("chunks", [])[:SHOW]:
        print(f"  {chunk['score']:.3f} {chunk['chunk_id']:26} [{', '.join(chunk['affected_packages'])}] {chunk['summary'][:70]}")


if __name__ == "__main__":
    main()
