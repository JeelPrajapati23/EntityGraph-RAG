from reachfix.evaluation.path_metrics import path_precision_recall


def test_exact_match_scores_one():
    result = path_precision_recall(["A --R--> B"], ["A --R--> B"])
    assert result == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "matched": ["A --R--> B"], "missing": [], "extra": []}


def test_partial_overlap():
    expected = ["A --R--> B", "A --R--> C"]
    actual = ["A --R--> B", "A --R--> D"]

    result = path_precision_recall(expected, actual)

    assert result["precision"] == 0.5  # 1 of 2 actual paths were correct
    assert result["recall"] == 0.5  # 1 of 2 expected paths were found
    assert result["matched"] == ["A --R--> B"]
    assert result["missing"] == ["A --R--> C"]
    assert result["extra"] == ["A --R--> D"]


def test_no_expected_paths_and_no_actual_paths_is_a_perfect_score():
    result = path_precision_recall([], [])
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_actual_paths_when_none_expected_is_zero_precision():
    result = path_precision_recall([], ["A --R--> B"])
    assert result["precision"] == 0.0  # everything returned was unwanted
    assert result["recall"] == 1.0  # vacuously — there was nothing to miss
    assert result["f1"] == 0.0


def test_no_actual_paths_when_some_expected_is_zero_recall():
    result = path_precision_recall(["A --R--> B"], [])
    assert result["precision"] == 1.0  # vacuously — nothing wrong was returned
    assert result["recall"] == 0.0  # but everything expected was missed
    assert result["f1"] == 0.0
