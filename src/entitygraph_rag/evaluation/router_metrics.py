"""Router accuracy: did the query get classified into the right retrieval route?"""


def router_accuracy(rows: list[dict]) -> float:
    """rows: [{"expected_route": ..., "actual_route": ...}, ...]. 0.0 if rows is empty."""
    if not rows:
        return 0.0
    correct = sum(1 for row in rows if row["expected_route"] == row["actual_route"])
    return correct / len(rows)
