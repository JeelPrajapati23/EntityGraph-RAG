"""Load every pipeline artifact the API serves from, once, at startup.

Same artifacts scripts/ask.py loads (chunks, resolved entities, graph,
vector index, schema, both provider clients) bundled into one object so
request handlers never touch the filesystem.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from groq import Groq
from huggingface_hub import InferenceClient

from ..extraction.schema import Schema, load_schema
from ..graph import GraphStore, NetworkXGraphStore
from ..llm_client import build_client
from ..retrieval import VectorIndex, build_embedding_client
from ..router import EntityLookup

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROCESSED_DIR = REPO_ROOT / "data" / "processed"


@dataclass
class Resources:
    chunks_by_id: dict
    entity_lookup: EntityLookup
    store: GraphStore
    index: VectorIndex
    schema: Schema
    client: Groq
    embedding_client: InferenceClient


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_resources(processed_dir: Path = DEFAULT_PROCESSED_DIR) -> Resources:
    chunks_path = processed_dir / "chunks.jsonl"
    entities_path = processed_dir / "entities.jsonl"
    graph_path = processed_dir / "graph.pkl"
    missing = [p.name for p in (chunks_path, entities_path, graph_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"missing {', '.join(missing)} in {processed_dir} — run build_chunks/resolve_entities/build_graph first"
        )

    return Resources(
        chunks_by_id={c["chunk_id"]: c for c in _load_jsonl(chunks_path)},
        entity_lookup=EntityLookup(_load_jsonl(entities_path)),
        store=NetworkXGraphStore.from_file(graph_path),
        index=VectorIndex.from_file(processed_dir / "chunk_index"),
        schema=load_schema(),
        client=build_client(),
        embedding_client=build_embedding_client(),
    )
