"""Compare advisory index variants on label-free retrieval checks.

Runs the package and vulnerability-class query sets from
entitygraph_rag.npm.retrieval_eval against each built index variant
(scripts/build_advisory_index.py, both --variant values) and reports
precision@k over distinct advisories. Query embeddings are cached in
.cache/embeddings/ like chunk embeddings.

Output: eval/results/advisory_retrieval.json

Usage:
    uv run python scripts/eval_advisory_retrieval.py [--k 5]
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from entitygraph_rag.npm import retrieval_eval as ev
from entitygraph_rag.npm.advisory_index import VARIANTS, index_path
from entitygraph_rag.npm.corpus import read_jsonl
from entitygraph_rag.retrieval import VectorIndex, build_embedding_client, embed_chunks
from entitygraph_rag.retrieval.windows import search_chunks

ROOT = Path(__file__).resolve().parent.parent
DEPGRAPH = ROOT / "data" / "processed" / "depgraph"
CACHE_ROOT = ROOT / ".cache" / "embeddings"
OUT_PATH = ROOT / "eval" / "results" / "advisory_retrieval.json"


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    chunks = read_jsonl(DEPGRAPH / "advisory_chunks.jsonl")
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    texts = ev.advisory_text(chunks)
    pkg_queries = ev.package_queries(chunks)
    queries = [q for q, _ in pkg_queries] + [q for q, _ in ev.CLASS_QUERIES]

    client = build_embedding_client()
    report = {"k": args.k, "variants": {}}
    for variant, options in VARIANTS.items():
        path = index_path(DEPGRAPH, variant)
        if not Path(f"{path}.ids.json").exists():
            print(f"  ! {variant} index not built; run scripts/build_advisory_index.py --variant {variant}")
            continue
        index = VectorIndex.from_file(path)
        # Queries go through the variant's own model (cached like chunks).
        ids, vectors = embed_chunks([{"chunk_id": f"query::{q}", "text": q} for q in queries], client=client,
                                    model_name=options.model, output_dimensionality=options.dimensions,
                                    cache_root=CACHE_ROOT)
        query_vectors = {i.removeprefix("query::"): v for i, v in zip(ids, vectors)}

        def top(query):
            # Over-fetch chunks, then keep the first k distinct advisories.
            hits = search_chunks(query, index=index, chunks_by_id=chunks_by_id, client=client,
                                 top_k=args.k * 3, query_vector=query_vectors[query])
            return ev.distinct_advisories(hits, args.k)

        pkg_scores = [ev.precision(top(q), lambda r, p=p: p in r["affected_packages"]) for q, p in pkg_queries]
        class_rows = []
        for q, pattern in ev.CLASS_QUERIES:
            score = ev.precision(top(q), ev.class_relevance(pattern, texts))
            class_rows.append({"query": q, "precision": round(score, 2),
                               "base_rate": round(ev.class_base_rate(pattern, texts), 2)})
        report["variants"][variant] = {
            "packages": ev.summarize(pkg_scores),
            "classes": ev.summarize([r["precision"] for r in class_rows]),
            "class_queries": class_rows,
        }

    if not report["variants"]:
        raise SystemExit("No index built; nothing to evaluate.")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"precision@{args.k} over distinct advisories ({len(pkg_queries)} package queries, "
          f"{len(ev.CLASS_QUERIES)} class queries)\n")
    for variant, r in report["variants"].items():
        print(f"{variant:16} packages {r['packages']['mean_precision']:.3f} "
              f"(all relevant {r['packages']['all_relevant']}, none {r['packages']['none_relevant']})   "
              f"classes {r['classes']['mean_precision']:.3f}")
    print(f"\nclass queries ({' / '.join(report['variants'])}; base = share of advisories that are relevant):")
    variants = report["variants"]
    for i, (q, _) in enumerate(ev.CLASS_QUERIES):
        cells = "  ".join(f"{v['class_queries'][i]['precision']:.2f}" for v in variants.values())
        base = next(iter(variants.values()))["class_queries"][i]["base_rate"]
        print(f"  {cells}  base {base:.2f}  {q}")
    print(f"\n-> {OUT_PATH.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
