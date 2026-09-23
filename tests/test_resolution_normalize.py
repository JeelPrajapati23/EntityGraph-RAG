from reachfix.resolution.normalize import normalize_name


def test_strips_common_corporate_suffix():
    assert normalize_name("NVIDIA Corporation") == "nvidia"


def test_strips_multi_word_suffix():
    assert normalize_name("ASML Holding N.V.") == "asml"


def test_strips_comma_separated_suffix():
    assert normalize_name("Advanced Micro Devices, Inc.") == "advanced micro devices"


def test_case_insensitive_and_whitespace_collapsed():
    assert normalize_name("  nvidia   corporation  ") == "nvidia"


def test_name_with_no_suffix_is_unchanged_but_lowercased():
    assert normalize_name("Hugging Face") == "hugging face"
