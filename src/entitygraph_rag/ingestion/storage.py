"""JSONL output for chunk records.

The one module a future Postgres/Neon swap would touch — chunking logic
never writes to disk directly.
"""

import dataclasses
import json
from pathlib import Path

from .schema import Chunk


def write_jsonl(path: Path, chunks: list[Chunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(dataclasses.asdict(chunk)) + "\n")
