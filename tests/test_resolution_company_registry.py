import pytest

from entitygraph_rag.resolution.company_registry import CompanyRecord, CompanyRegistry, load_company_registry


@pytest.fixture
def registry():
    return CompanyRegistry(
        [
            CompanyRecord(name="NVIDIA Corporation", ticker="NVDA", sector="semiconductors", filer_type="domestic"),
            CompanyRecord(
                name="Taiwan Semiconductor Manufacturing Company Limited",
                ticker="TSM",
                sector="semiconductors",
                filer_type="foreign_private_issuer",
            ),
        ]
    )


def test_matches_exact_ticker(registry):
    assert registry.match("NVDA").ticker == "NVDA"


def test_matches_normalized_full_name(registry):
    assert registry.match("NVIDIA").ticker == "NVDA"
    assert registry.match("nvidia corporation").ticker == "NVDA"


def test_matches_curated_alias(registry):
    assert registry.match("TSMC").ticker == "TSM"


def test_matches_fuzzy_close_name(registry):
    # Minor real-world variation (missing "Limited") should still fuzzy-match.
    assert registry.match("Taiwan Semiconductor Manufacturing Company").ticker == "TSM"


def test_no_match_for_unrelated_company(registry):
    assert registry.match("Hugging Face") is None


def test_real_companies_yaml_loads_and_matches_all_tickers():
    registry = load_company_registry()
    for company in registry.companies:
        assert registry.match(company.ticker) is company
        assert registry.match(company.name) is company
