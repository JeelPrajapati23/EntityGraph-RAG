from collections import Counter

from entitygraph_rag.resolution.cluster import cluster_names


def test_identical_names_cluster_together():
    counts = Counter({"Hugging Face": 3, "hugging face": 1})
    result = cluster_names(counts)
    assert result["Hugging Face"] == result["hugging face"]


def test_close_variants_fuzzy_cluster_together():
    counts = Counter({"Securities and Exchange Commission": 2, "Securities & Exchange Commission": 1})
    result = cluster_names(counts)
    assert result["Securities and Exchange Commission"] == result["Securities & Exchange Commission"]


def test_canonical_name_is_most_frequent_surface_form():
    counts = Counter({"Hugging Face Inc.": 1, "Hugging Face": 5})
    result = cluster_names(counts)
    assert result["Hugging Face Inc."] == "Hugging Face"
    assert result["Hugging Face"] == "Hugging Face"


def test_dissimilar_names_do_not_cluster():
    counts = Counter({"Hugging Face": 2, "OpenAI": 2})
    result = cluster_names(counts)
    assert result["Hugging Face"] != result["OpenAI"]
