"""Load every artifact the API serves from, once, at startup.

The same artifacts scripts/ask_depgraph.py loads (the DepGraph router
context: graph, node lookup, advisory index and chunks, remediation release
metadata; plus the schema and the Groq client), bundled into one object so
request handlers never touch the filesystem.
"""

from dataclasses import dataclass
from pathlib import Path

from groq import Groq

from ..depgraph import DepGraphContext, load_context
from ..extraction.schema import Schema, load_schema
from ..llm_client import build_client
from ..npm.advisory_index import DEFAULT_VARIANT, index_path
from ..retrieval import build_embedding_client

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEPGRAPH_DIR = REPO_ROOT / "data" / "processed" / "depgraph"


@dataclass
class Resources:
    ctx: DepGraphContext
    schema: Schema
    client: Groq


def load_resources(depgraph_dir: Path = DEFAULT_DEPGRAPH_DIR, variant: str = DEFAULT_VARIANT) -> Resources:
    required = [depgraph_dir / name for name in ("graph.pkl", "nodes.jsonl", "advisory_chunks.jsonl")]
    missing = [p.name for p in required if not p.exists()]
    if not Path(f"{index_path(depgraph_dir, variant)}.vectors.npy").exists():
        missing.append(f"advisory index {variant!r}")
    if missing:
        raise FileNotFoundError(f"missing {', '.join(missing)} in {depgraph_dir}; run the build scripts "
                                f"(build_depgraph.py, build_advisory_index.py) first")

    return Resources(
        ctx=load_context(depgraph_dir, build_embedding_client(), variant),
        schema=load_schema(),
        client=build_client(),
    )
