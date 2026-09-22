"""Graph-path precision/recall: does a route's evidence match the golden path set?

Compares the human-readable graph-path strings synthesis/citations.py
already produces (graph_paths_for_result) against a golden question's
expected_graph_paths, both treated as unordered sets of edge strings —
per the project plan, exact path match is too strict, so this scores on
edge overlap instead.
"""


def path_precision_recall(expected: list[str], actual: list[str]) -> dict:
    expected_set, actual_set = set(expected), set(actual)
    overlap = expected_set & actual_set

    # Vacuous truth on the empty side: an empty actual set contains no wrong
    # paths (precision 1.0), and an empty expected set has nothing to miss
    # (recall 1.0) — regardless of what the other set holds.
    precision = len(overlap) / len(actual_set) if actual_set else 1.0
    recall = len(overlap) / len(expected_set) if expected_set else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "matched": sorted(overlap),
        "missing": sorted(expected_set - actual_set),
        "extra": sorted(actual_set - expected_set),
    }
