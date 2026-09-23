"""Build the canonical node table of schema v2, plus the registry-derived edges.

Package names and versions are already canonical in npm, so resolution here
is about giving every node one id and making sure every edge endpoint
points at a node:

- Package / PackageVersion: every corpus version (`in_tree`), plus every
  FIXED_IN target (`in_tree` false). `is_root` marks the corpus roots.
- Vulnerability: one node per OSV record. Records that alias each other (an
  advisory and its incomplete-fix follow-up share CVE ids) stay separate,
  because each has its own ranges and fix. NodeLookup returns all of them
  for a shared CVE.
- Maintainer, License: from the registry packuments.

Edges built here, all deterministic from the registry: VERSION_OF,
MAINTAINED_BY (current maintainers only; the registry has no history) and
LICENSED_UNDER (one edge per license in an SPDX expression, carrying the
whole expression).
"""

from collections.abc import Callable, Iterable

from .licenses import parse_license
from .projects import Project
from .registry import packument_url
from .vulnerabilities import OSV_WEB, npm_affected, package_id, version_id

CVSS_TYPES = ("CVSS_V4", "CVSS_V3", "CVSS_V2")  # preference order for `cvss_vector`

PackumentLookup = Callable[[str], dict | None]


def maintainer_id(username: str) -> str:
    return f"npm-user:{username}"


def license_id(spdx_id: str) -> str:
    return f"license:{spdx_id}"


def node(node_id: str, node_type: str, display_name: str, known_as: Iterable[str], **properties) -> dict:
    """`known_as` becomes the node's lookup `aliases`; `properties` are the schema properties."""
    return {"node_id": node_id, "node_type": node_type, "name": display_name,
            "aliases": sorted(set(known_as)), "properties": properties}


def registry_edge(relation: str, subject: str, obj: str, package_name: str, **properties) -> dict:
    return {"relation": relation, "extraction_method": "deterministic", "subject": subject, "object": obj,
            **properties, "source_doc_id": f"npm-registry:{package_name}", "source_url": packument_url(package_name)}


def cvss_vector(record: dict) -> str | None:
    scores = {s["type"]: s["score"] for s in record.get("severity", [])}
    return next((scores[t] for t in CVSS_TYPES if t in scores), None)


def vulnerability_node(record: dict) -> dict:
    osv_id = record["id"]
    return node(
        osv_id, "Vulnerability", osv_id, [osv_id, *record.get("aliases", [])],
        osv_id=osv_id,
        aliases=record.get("aliases", []),
        summary=record.get("summary", ""),
        severity=record.get("database_specific", {}).get("severity"),
        cvss_vector=cvss_vector(record),
        published_at=record.get("published"),
        modified_at=record.get("modified"),
        withdrawn_at=record.get("withdrawn"),
        source_url=OSV_WEB + osv_id,
    )


def build_nodes(
    corpus: dict[tuple[str, str], set[str]],
    packuments: PackumentLookup,
    advisories: list[dict],
    projects: list[Project],
    fixed_in_targets: Iterable[tuple[str, str]],
) -> tuple[list[dict], list[dict]]:
    """Return (nodes, VERSION_OF + MAINTAINED_BY + LICENSED_UNDER edges)."""
    roots = {(p.name, p.version) for p in projects}
    versions = {nv: True for nv in corpus}
    for nv in fixed_in_targets:
        versions.setdefault(nv, False)
    names = {name for name, _ in versions} | {a["package"]["name"] for r in advisories for a in npm_affected(r)}

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    for name in sorted(names):
        nodes[package_id(name)] = node(package_id(name), "Package", name, [name], name=name, ecosystem="npm")
        packument = packuments(name)
        if packument is None:
            continue
        for username in packument["maintainers"]:
            nodes.setdefault(maintainer_id(username),
                             node(maintainer_id(username), "Maintainer", username, [username], username=username))
            edges.append(registry_edge("MAINTAINED_BY", package_id(name), maintainer_id(username), name))

    for (name, version), in_tree in sorted(versions.items()):
        vid = version_id(name, version)
        packument = packuments(name) or {}
        meta = packument.get("versions", {}).get(version, {})
        nodes[vid] = node(
            vid, "PackageVersion", f"{name}@{version}", [f"{name}@{version}"],
            name=name, ecosystem="npm", version=version,
            published_at=packument.get("time", {}).get(version),
            deprecated=meta.get("deprecated"),
            is_root=(name, version) in roots,
            in_tree=in_tree,
            # None when there is no packument to check against.
            published=(version in packument["all_versions"]) if packument else None,
            lockfile_doc_ids=sorted(corpus.get((name, version), ())),
        )
        edges.append(registry_edge("VERSION_OF", vid, package_id(name), name))

        parsed = parse_license(meta.get("license"))
        if parsed is None:
            continue
        for spdx_id in parsed.ids:
            nodes.setdefault(license_id(spdx_id), node(license_id(spdx_id), "License", spdx_id, [spdx_id], spdx_id=spdx_id))
            edges.append(registry_edge("LICENSED_UNDER", vid, license_id(spdx_id), name,
                                       expression=parsed.expression, operator=parsed.operator))

    for record in advisories:
        nodes[record["id"]] = vulnerability_node(record)

    return list(nodes.values()), edges


def dangling_endpoints(nodes: list[dict], edges: Iterable[dict]) -> list[tuple[str, str]]:
    """(relation, endpoint id) for every edge endpoint that isn't a node."""
    ids = {n["node_id"] for n in nodes}
    return [(e["relation"], end) for e in edges for end in (e["subject"], e["object"]) if end not in ids]


def dependency_edge_endpoints(edge: dict) -> dict:
    """A dependency_edges.jsonl row as a subject/object edge, for endpoint checks and graph loading."""
    return {**edge, "relation": "DEPENDS_ON",
            "subject": version_id(edge["from_name"], edge["from_version"]),
            "object": version_id(edge["to_name"], edge["to_version"])}
