"""Greedy fuzzy clustering for entities with no fixed canonical registry.

Used for every non-Company node type, and for Company mentions outside the
fixed 20-company universe. Each name is compared only against existing
cluster representatives, not every other name (O(n * k), not O(n^2)) —
fine at this corpus's scale (hundreds, not millions, of unique names per
type).
"""

from collections import Counter

from rapidfuzz import fuzz, process

from .normalize import normalize_name

FUZZY_CLUSTER_THRESHOLD = 90


def cluster_names(counts: Counter) -> dict[str, str]:
    """Return {raw_name: canonical_name} for every name key in `counts`.

    Processes names most-frequent-first (via `counts`) so the canonical
    representative of each cluster is its most common surface form, not
    just whichever happened to appear first.
    """
    ordered = [name for name, _ in counts.most_common()]

    normalized_reps: dict[str, str] = {}  # normalized form -> canonical raw name
    assignment: dict[str, str] = {}

    for name in ordered:
        normalized = normalize_name(name)

        if normalized in normalized_reps:
            assignment[name] = normalized_reps[normalized]
            continue

        best = (
            process.extractOne(normalized, normalized_reps.keys(), scorer=fuzz.token_sort_ratio)
            if normalized_reps
            else None
        )

        if best is not None and best[1] >= FUZZY_CLUSTER_THRESHOLD:
            assignment[name] = normalized_reps[best[0]]
        else:
            normalized_reps[normalized] = name
            assignment[name] = name

    return assignment
