import pytest

from reachfix.resolution.company_registry import CompanyRecord, CompanyRegistry
from reachfix.resolution.resolve import apply_resolution, resolve_entities

TRIPLES = [
    {
        "subject": "TSMC", "subject_type": "Company", "relation": "SUPPLIES",
        "object": "NVIDIA", "object_type": "Company", "confidence": 0.9,
        "source_chunk_id": "c1", "source_doc_id": "d1", "extracted_at": "t",
    },
    {
        "subject": "TSMC", "subject_type": "Company", "relation": "SUPPLIES",
        "object": "NVIDIA Corporation", "object_type": "Company", "confidence": 0.9,
        "source_chunk_id": "c2", "source_doc_id": "d1", "extracted_at": "t",
    },
    {
        "subject": "NVIDIA", "subject_type": "Company", "relation": "INVESTED_IN",
        "object": "Hugging Face", "object_type": "Company", "confidence": 0.8,
        "source_chunk_id": "c3", "source_doc_id": "d1", "extracted_at": "t",
    },
    {
        "subject": "NVIDIA Corporation", "subject_type": "Company", "relation": "INVESTED_IN",
        "object": "Hugging Face Inc.", "object_type": "Company", "confidence": 0.8,
        "source_chunk_id": "c4", "source_doc_id": "d1", "extracted_at": "t",
    },
]


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


def test_known_company_variants_resolve_to_same_canonical_entity(registry):
    resolved = resolve_entities(TRIPLES, company_registry=registry)

    nvidia_short = resolved[("NVIDIA", "Company")]
    nvidia_full = resolved[("NVIDIA Corporation", "Company")]
    assert nvidia_short.entity_id == nvidia_full.entity_id
    assert nvidia_short.canonical_name == "NVIDIA Corporation"


def test_unregistered_company_variants_cluster_together(registry):
    resolved = resolve_entities(TRIPLES, company_registry=registry)

    hf_short = resolved[("Hugging Face", "Company")]
    hf_full = resolved[("Hugging Face Inc.", "Company")]
    assert hf_short.entity_id == hf_full.entity_id


def test_resolved_entity_carries_all_surface_forms_as_aliases(registry):
    resolved = resolve_entities(TRIPLES, company_registry=registry)
    nvidia = resolved[("NVIDIA", "Company")]
    assert set(nvidia.aliases) == {"NVIDIA", "NVIDIA Corporation"}


def test_apply_resolution_adds_subject_and_object_ids(registry):
    resolved = resolve_entities(TRIPLES, company_registry=registry)
    edges = apply_resolution(TRIPLES, resolved)

    assert edges[0]["subject_id"] == edges[1]["subject_id"]  # both TSMC
    assert edges[0]["object_id"] == resolved[("NVIDIA Corporation", "Company")].entity_id
    # original raw text is preserved alongside the canonical id
    assert edges[0]["subject"] == "TSMC"
