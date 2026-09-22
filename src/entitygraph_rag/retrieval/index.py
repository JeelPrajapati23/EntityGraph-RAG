"""Brute-force cosine-similarity vector index over a local NumPy array.

Flat brute-force search is fine at this corpus's scale (hundreds to low
thousands of chunks) and keeps the dependency footprint light — an ANN
index (FAISS or similar) is a drop-in swap later if the corpus outgrows
this, without changing anything upstream (VectorIndex.search is the only
surface callers use).
"""

import json
from pathlib import Path

import numpy as np


class VectorIndex:
    def __init__(self, chunk_ids: list[str], vectors: np.ndarray):
        vectors = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # guard a zero-vector chunk rather than dividing by zero
        self.chunk_ids = chunk_ids
        self.vectors = vectors / norms  # pre-normalized so search is a plain dot product

    def search(self, query_vector: list[float] | np.ndarray, *, top_k: int = 5) -> list[tuple[str, float]]:
        query = np.asarray(query_vector, dtype=np.float32)
        query = query / (np.linalg.norm(query) or 1.0)

        scores = self.vectors @ query
        top_k = min(top_k, len(self.chunk_ids))
        if top_k == 0:
            return []

        top_indices = np.argpartition(-scores, top_k - 1)[:top_k]
        top_indices = top_indices[np.argsort(-scores[top_indices])]
        return [(self.chunk_ids[i], float(scores[i])) for i in top_indices]

    def save_to_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(f"{path}.vectors.npy", self.vectors)
        Path(f"{path}.ids.json").write_text(json.dumps(self.chunk_ids), encoding="utf-8")

    @classmethod
    def from_file(cls, path: Path) -> "VectorIndex":
        vectors = np.load(f"{path}.vectors.npy")
        chunk_ids = json.loads(Path(f"{path}.ids.json").read_text(encoding="utf-8"))
        return cls(chunk_ids, vectors)
