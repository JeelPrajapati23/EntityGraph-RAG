"""Golden-set schema and loader for evaluation (see eval/golden_set.yaml).

Each entry pins a question to the route it should take and, where the
answer is a crisp graph lookup, the exact set of human-readable graph-path
strings (synthesis/citations.py's format) a correct run should produce.
This is the ground truth router-accuracy and path-precision/recall are
scored against (see runner.py). expected_graph_paths is left empty for
semantic and graph_guided_hybrid questions, whose evidence set is a broad
neighborhood rather than a small hand-verifiable one — those routes are
scored on router accuracy and LLM-judged answer quality only (see judge.py).
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

DEFAULT_GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent.parent.parent / "eval" / "golden_set.yaml"


class GoldenQuestion(BaseModel):
    id: str
    question: str
    expected_route: Literal["semantic", "relational", "graph_guided_hybrid"]
    expected_answer: str
    expected_graph_paths: list[str] = []
    notes: str | None = None


def load_golden_set(path: Path = DEFAULT_GOLDEN_SET_PATH) -> list[GoldenQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [GoldenQuestion.model_validate(item) for item in raw["questions"]]
