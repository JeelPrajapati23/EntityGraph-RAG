"""Run a classified DepGraph query against the graph, the advisory index, or both.

Glue only: every retrieval step is an existing function (graph/exposure.py,
GraphStore.neighbors, retrieval/windows.search_chunks). Result rows carry
the node ids, paths and provenance that answer synthesis needs, so it never
has to query the graph again.

A project is a PackageVersion. Walks from it are scoped to one lockfile:
its own if it is a corpus root, otherwise each lockfile it is installed in.
A bare package name ("express") means its corpus-root versions if any,
else every version in a tree.
"""

from dataclasses import dataclass, field

from huggingface_hub import InferenceClient
from pydantic import BaseModel

from ..graph import GraphStore
from ..graph.exposure import dependency_paths, exposed_lockfiles, exposure
from ..npm.advisory_index import DEFAULT_VARIANT, embed_query
from ..npm.graph_load import LOCKFILE_DOC_PREFIX, root_of_lockfile
from ..npm.lookup import NodeLookup
from ..retrieval import VectorIndex
from ..retrieval.windows import search_chunks

MAX_ROWS = 200  # cap on result rows per query; synthesis only needs the top of the list


@dataclass
class DepGraphContext:
    store: GraphStore
    lookup: NodeLookup
    index: VectorIndex
    chunks_by_id: dict[str, dict]
    embedding_client: InferenceClient | None
    variant: str = DEFAULT_VARIANT
    chunks_by_advisory: dict[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        self.chunks_by_advisory = {}
        for chunk_id, chunk in self.chunks_by_id.items():
            self.chunks_by_advisory.setdefault(chunk["doc_id"], []).append(chunk_id)


def node_type(ctx: DepGraphContext, node_id: str) -> str | None:
    entity = ctx.store.get_entity(node_id)
    return entity["entity_type"] if entity else None


def named(ctx: DepGraphContext, node_id: str) -> dict:
    entity = ctx.store.get_entity(node_id) or {}
    return {"node_id": node_id, "name": entity.get("canonical_name", node_id), "type": entity.get("entity_type")}


def resolve(ctx: DepGraphContext, names: list[str]) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """([(name as written, node ids)], warnings for names that matched nothing)."""
    resolved, warnings = [], []
    for name in names:
        ids = ctx.lookup.resolve(name)
        if ids:
            resolved.append((name, ids))
        else:
            warnings.append(f"no package, version or advisory matches {name!r}")
    return resolved, warnings


def project_versions(ctx: DepGraphContext, node_id: str) -> list[str]:
    """A PackageVersion as itself; a Package as its root versions, else all its in-tree versions."""
    kind = node_type(ctx, node_id)
    if kind == "PackageVersion":
        return [node_id]
    if kind != "Package":
        return []
    versions = [e["entity_id"] for e in ctx.store.neighbors(node_id, relation="VERSION_OF", direction="in")]
    in_tree = [v for v in versions if ctx.store.get_entity(v)["properties"].get("in_tree")]
    roots = [v for v in in_tree if ctx.store.get_entity(v)["properties"].get("is_root")]
    return sorted(roots or in_tree)


def lockfiles_for(ctx: DepGraphContext, version_id: str) -> list[str]:
    """The lockfile a walk from this version should follow: its own if it's a root, else every one containing it."""
    props = (ctx.store.get_entity(version_id) or {}).get("properties", {})
    own = LOCKFILE_DOC_PREFIX + version_id.removeprefix("npm:")
    if props.get("is_root"):
        return [own]
    return list(props.get("lockfile_doc_ids", []))


def split_entities(ctx: DepGraphContext, resolved) -> tuple[list[str], set[str]]:
    """(project version ids in query order, advisory ids) from resolved entities."""
    projects, advisories = [], set()
    for _, ids in resolved:
        for node_id in ids:
            kind = node_type(ctx, node_id)
            if kind == "Vulnerability":
                advisories.add(node_id)
            elif kind in ("Package", "PackageVersion"):
                projects.extend(v for v in project_versions(ctx, node_id) if v not in projects)
    return projects, advisories


def advisory_row(ctx: DepGraphContext, vuln_id: str) -> dict:
    props = (ctx.store.get_entity(vuln_id) or {}).get("properties", {})
    return {"vulnerability_id": vuln_id, "aliases": props.get("aliases", []), "severity": props.get("severity"),
            "summary": props.get("summary"), "source_url": props.get("source_url")}


def run_exposure(ctx: DepGraphContext, resolved) -> dict:
    projects, advisories = split_entities(ctx, resolved)
    rows = []
    for project in projects:
        for lockfile in lockfiles_for(ctx, project):
            for hit in exposure(ctx.store, project, lockfile, vulnerability_ids=advisories or None):
                rows.append({"project": project, "lockfile_doc_id": lockfile, **hit,
                             **advisory_row(ctx, hit["vulnerability_id"])})
    rows.sort(key=lambda r: (r["depth"], r["vulnerability_id"]))
    return {"pattern": "exposure", "projects": projects, "advisories": sorted(advisories), "results": rows[:MAX_ROWS],
            "total_results": len(rows)}


def run_affected_projects(ctx: DepGraphContext, resolved) -> dict:
    _, advisories = split_entities(ctx, resolved)
    rows = []
    for vuln_id in sorted(advisories):
        for lockfile, versions in exposed_lockfiles(ctx.store, vuln_id).items():
            root = root_of_lockfile(lockfile)
            for hit in exposure(ctx.store, root, lockfile, vulnerability_ids={vuln_id}):
                rows.append({"project": root, "lockfile_doc_id": lockfile, **hit, **advisory_row(ctx, vuln_id)})
    rows.sort(key=lambda r: (r["vulnerability_id"], r["project"], r["depth"]))
    return {"pattern": "affected_projects", "advisories": sorted(advisories), "results": rows[:MAX_ROWS],
            "total_results": len(rows)}


def run_dependency_path(ctx: DepGraphContext, resolved) -> dict:
    """Paths from the first named project to every version of the second named package."""
    if len(resolved) < 2:
        return {"pattern": "dependency_path", "results": [], "warning": "need a project and a dependency"}
    projects, _ = split_entities(ctx, resolved[:1])
    targets = set()
    for node_id in resolved[1][1]:
        if node_type(ctx, node_id) == "Package":  # any version of it, wherever it sits in the tree
            targets.update(e["entity_id"] for e in ctx.store.neighbors(node_id, relation="VERSION_OF", direction="in"))
        else:
            targets.add(node_id)
    rows = []
    for project in projects:
        for lockfile in lockfiles_for(ctx, project):
            paths = dependency_paths(ctx.store, project, lockfile)
            rows.extend({"project": project, "lockfile_doc_id": lockfile, "version_id": v, "path": paths[v],
                         "depth": len(paths[v]) - 1} for v in sorted(targets & set(paths)))
    rows.sort(key=lambda r: (r["depth"], r["version_id"]))
    return {"pattern": "dependency_path", "results": rows[:MAX_ROWS], "total_results": len(rows)}


def run_neighbors(ctx: DepGraphContext, resolved, relation: str | None) -> dict:
    rows = []
    for _, ids in resolved:
        for node_id in ids:
            for edge in ctx.store.neighbors(node_id, relation=relation, direction="both"):
                rows.append({"source": named(ctx, node_id), **named(ctx, edge["entity_id"]),
                             "relation": edge["relation"], "direction": edge["direction"],
                             "confidence": edge["confidence"], "provenance": edge["provenance"],
                             "properties": edge.get("properties", {})})
    return {"pattern": "neighbors", "relation": relation, "results": rows[:MAX_ROWS], "total_results": len(rows)}


def run_relational(ctx: DepGraphContext, decision: BaseModel, resolved) -> dict:
    pattern = decision.pattern or "neighbors"
    if pattern == "exposure":
        return run_exposure(ctx, resolved)
    if pattern == "affected_projects":
        return run_affected_projects(ctx, resolved)
    if pattern == "dependency_path":
        return run_dependency_path(ctx, resolved)
    return run_neighbors(ctx, resolved, decision.relation)


def semantic_chunks(ctx: DepGraphContext, query: str, top_k: int, candidates: set[str] | None = None) -> list[dict]:
    return search_chunks(query, index=ctx.index, chunks_by_id=ctx.chunks_by_id, client=ctx.embedding_client,
                         top_k=top_k, candidate_chunk_ids=candidates,
                         query_vector=embed_query(ctx.embedding_client, query, ctx.variant))


def graph_advisories(ctx: DepGraphContext, resolved) -> set[str]:
    """Advisories the named entities point at.

    An advisory is itself. A package name means the advisories affecting that
    package ("what vulnerabilities has lodash had?"). A version means every
    advisory reachable in its dependency tree ("... the vulnerable packages
    in express@4.17.1").
    """
    found = set()
    for _, ids in resolved:
        for node_id in ids:
            kind = node_type(ctx, node_id)
            if kind == "Vulnerability":
                found.add(node_id)
            elif kind == "Package":
                found.update(e["entity_id"] for e in
                             ctx.store.neighbors(node_id, relation="AFFECTS_VERSION_RANGE", direction="in"))
            elif kind == "PackageVersion":
                for lockfile in lockfiles_for(ctx, node_id):
                    found.update(hit["vulnerability_id"] for hit in exposure(ctx.store, node_id, lockfile))
    return found


def run_graph_guided_hybrid(ctx: DepGraphContext, query: str, resolved, top_k: int) -> dict:
    advisories = graph_advisories(ctx, resolved)
    candidates = {c for a in advisories for c in ctx.chunks_by_advisory.get(a, [])}
    result = {"advisories": [advisory_row(ctx, a) for a in sorted(advisories)][:MAX_ROWS]}
    if not candidates:
        # Nothing in the graph to scope by: fall back to an unscoped semantic search.
        result["warning"] = "no advisories linked to the named entities; searched all advisories"
    result["chunks"] = semantic_chunks(ctx, query, top_k, candidates or None)
    return result
