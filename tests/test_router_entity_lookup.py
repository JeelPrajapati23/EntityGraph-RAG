from reachfix.router.entity_lookup import EntityLookup

ENTITIES = [
    {"entity_id": "Company:nvidia-corporation", "canonical_name": "NVIDIA Corporation", "entity_type": "Company", "aliases": ["NVIDIA", "NVIDIA Corporation"]},
    {"entity_id": "Company:tsmc", "canonical_name": "Taiwan Semiconductor Manufacturing Company Limited", "entity_type": "Company", "aliases": ["TSMC"]},
]


def test_resolves_exact_canonical_name():
    lookup = EntityLookup(ENTITIES)
    assert lookup.resolve("NVIDIA Corporation") == "Company:nvidia-corporation"


def test_resolves_known_alias():
    lookup = EntityLookup(ENTITIES)
    assert lookup.resolve("NVIDIA") == "Company:nvidia-corporation"
    assert lookup.resolve("TSMC") == "Company:tsmc"


def test_resolves_case_insensitively():
    lookup = EntityLookup(ENTITIES)
    assert lookup.resolve("nvidia") == "Company:nvidia-corporation"


def test_resolves_close_fuzzy_typo():
    lookup = EntityLookup(ENTITIES)
    assert lookup.resolve("NVDIA") == "Company:nvidia-corporation"  # missing "I", not an exact normalized match


def test_unrelated_name_returns_none():
    lookup = EntityLookup(ENTITIES)
    assert lookup.resolve("Hugging Face") is None


def test_empty_lookup_returns_none():
    lookup = EntityLookup([])
    assert lookup.resolve("anything") is None
