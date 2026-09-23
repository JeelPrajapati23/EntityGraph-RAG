"""Sanity checks for the DepGraph Phase 0 files: schema/v2.yaml and config/projects.yaml."""

import datetime
from pathlib import Path

import yaml

from reachfix.extraction.schema import load_schema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_V2 = ROOT / "schema" / "v2.yaml"
PROJECTS = ROOT / "config" / "projects.yaml"

EXTRACTION_METHODS = {"deterministic", "derived", "llm"}


def test_v2_loads_with_existing_loader():
    schema = load_schema(SCHEMA_V2)

    assert schema.version == 2
    assert "PackageVersion" in schema.node_types
    assert schema.allowed_subject_types("DEPENDS_ON") == {"PackageVersion"}
    assert schema.allowed_object_types("HAS_VULNERABILITY") == {"Vulnerability"}


def test_v2_edges_declare_extraction_method_and_reference_known_nodes():
    raw = yaml.safe_load(SCHEMA_V2.read_text(encoding="utf-8"))
    schema = load_schema(SCHEMA_V2)

    for name, edge in schema.edge_types.items():
        assert raw["edge_types"][name]["extraction"] in EXTRACTION_METHODS, name
        assert set(edge.subject_types) <= set(schema.node_types), name
        assert set(edge.object_types) <= set(schema.node_types), name


def test_v2_only_exploit_conditions_are_llm_extracted():
    raw = yaml.safe_load(SCHEMA_V2.read_text(encoding="utf-8"))
    llm_edges = {name for name, body in raw["edge_types"].items() if body["extraction"] == "llm"}

    assert llm_edges == {"EXPLOITABLE_WHEN"}


def test_projects_yaml_is_well_formed():
    raw = yaml.safe_load(PROJECTS.read_text(encoding="utf-8"))
    projects = raw["projects"]

    assert raw["ecosystem"] == "npm"
    assert 15 <= len(projects) <= 25
    assert len({p["name"] for p in projects}) == len(projects)
    for p in projects:
        assert isinstance(p["version"], str), p["name"]  # unquoted 4.10 would parse as a float
        assert isinstance(p["resolve_before"], datetime.date), p["name"]
