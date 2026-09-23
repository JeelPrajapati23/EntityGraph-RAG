from reachfix.evaluation.router_metrics import router_accuracy


def test_router_accuracy_all_correct():
    rows = [{"expected_route": "semantic", "actual_route": "semantic"}, {"expected_route": "relational", "actual_route": "relational"}]
    assert router_accuracy(rows) == 1.0


def test_router_accuracy_partial():
    rows = [
        {"expected_route": "semantic", "actual_route": "semantic"},
        {"expected_route": "relational", "actual_route": "semantic"},
    ]
    assert router_accuracy(rows) == 0.5


def test_router_accuracy_empty_is_zero():
    assert router_accuracy([]) == 0.0
