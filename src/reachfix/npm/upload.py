"""Layer an uploaded package-lock.json over the corpus graph.

The upload's versions and DEPENDS_ON edges go into a graph.overlay store on
top of the corpus graph, plus HAS_VULNERABILITY edges from matching each
installed version against the advisories already in the graph (the same
OSV range matching as vulnerabilities.build_vulnerability_edges). Exposure
and remediation then run unchanged, scoped to the upload's own lockfile
doc id.

A corpus lockfile's root entry is a scratch project that installed one
corpus package, so its dependencies are not edges. An upload's root entry
is the user's own project: its dependencies, devDependencies included, are
the direct edges, and remediation edits its package.json rather than
upgrading it.

Coverage: advisories were fetched from OSV for the corpus's exact
(name, version) pairs. Any other version is matched against the advisories
we hold for its package, but OSV may know more, so it is reported as
unchecked.
"""

import hashlib
import json
from dataclasses import dataclass, field

from ..graph.overlay import OverlayGraphStore
from ..graph.store import GraphStore
from .dependencies import resolve_dependencies, resolve_install_path, split_alias
from .lockfile import NODE_MODULES, check_lockfile, installed_packages
from .remediation import package_advisories
from .versions import is_affected, satisfies
from .vulnerabilities import OSV_WEB, version_id

UPLOAD_DOC_PREFIX = "lockfile:upload:"
PROJECT_PREFIX = "project:"
MAX_PACKAGES = 20_000
MAX_LISTED = 50
# package.json field -> dependency_type. "dev" only occurs on an upload's root edges.
ROOT_DEPENDENCY_FIELDS = (("dependencies", "prod"), ("devDependencies", "dev"),
                          ("optionalDependencies", "optional"), ("peerDependencies", "peer"))


@dataclass
class Upload:
    lockfile_doc_id: str
    root_id: str
    name: str
    version: str | None
    store: OverlayGraphStore
    install_paths: dict[str, list[str]]  # version id -> every install path of that version
    dev_only: set[str]                   # versions npm installed only for devDependencies
    unchecked: list[str]                 # versions OSV was never queried for (see module docstring)
    warnings: list[str] = field(default_factory=list)

    def coverage(self) -> dict:
        return {"versions": len(self.install_paths), "checked": len(self.install_paths) - len(self.unchecked),
                "unchecked": len(self.unchecked), "unchecked_examples": self.unchecked[:MAX_LISTED]}


def upload_doc_id(lock: dict) -> str:
    """Content-addressed, so the same lockfile always gets the same id."""
    digest = hashlib.sha256(json.dumps(lock, sort_keys=True).encode("utf-8")).hexdigest()
    return UPLOAD_DOC_PREFIX + digest[:16]


def _range_satisfied(version: str, spec: str) -> bool:
    try:
        return satisfies(version, split_alias(spec))
    except (ValueError, TypeError):
        return False  # a git/file/URL spec


def _affected(version: str, ranges: dict) -> bool:
    try:
        return is_affected(version, ranges)
    except (ValueError, TypeError):
        return False  # a non-semver version string


def load_upload(base: GraphStore, lock: object) -> Upload:
    """Validate an uploaded lockfile and build its overlay graph. Raises ValueError on a malformed upload."""
    check_lockfile(lock, "upload")
    if len(lock["packages"]) > MAX_PACKAGES:
        raise ValueError(f"upload: {len(lock['packages'])} packages; the limit is {MAX_PACKAGES}")
    try:
        installed = installed_packages(lock)
        deps = resolve_dependencies(lock)
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"upload: malformed `packages` entry ({e!r})") from e

    root_entry = lock["packages"].get("") or {}
    name = root_entry.get("name") or lock.get("name") or "project"
    version = root_entry.get("version") or lock.get("version")
    doc_id = upload_doc_id(lock)
    root_id = PROJECT_PREFIX + name + (f"@{version}" if version else "")
    store = OverlayGraphStore(base)
    store.upsert_entity({"entity_id": root_id, "entity_type": "Project",
                         "canonical_name": name + (f"@{version}" if version else ""), "aliases": [],
                         "properties": {"name": name, "version": version, "is_root": True,
                                        "lockfile_doc_ids": [doc_id]}})

    install_paths: dict[str, list[str]] = {}
    for pkg in installed:
        vid = version_id(pkg.name, pkg.version)
        if vid not in install_paths and store.get_entity(vid) is None:
            store.upsert_entity({"entity_id": vid, "entity_type": "PackageVersion",
                                 "canonical_name": f"{pkg.name}@{pkg.version}", "aliases": [f"{pkg.name}@{pkg.version}"],
                                 "properties": {"name": pkg.name, "ecosystem": "npm", "version": pkg.version,
                                                "in_tree": False, "uploaded": True}})
        install_paths.setdefault(vid, []).append(pkg.path)
    dev_only = {vid for vid, paths in install_paths.items() if all(lock["packages"][p].get("dev") for p in paths)}

    def depends_on(subject: str, dep_name: str, spec: str, dep_type: str, target) -> None:
        store.upsert_edge({
            "subject_id": subject, "relation": "DEPENDS_ON", "object_id": version_id(target.name, target.version),
            "provenance": [{"source_doc_id": doc_id, "extraction_method": "deterministic", "confidence": 1.0}],
            "properties": {"dep_name": dep_name, "version_range": split_alias(spec), "declared_spec": spec,
                           "dependency_type": dep_type, "range_satisfied": _range_satisfied(target.version, spec),
                           "lockfile_doc_ids": [doc_id]},
        })

    by_path = {p.path: p for p in installed}
    unresolved = []
    for field_name, dep_type in ROOT_DEPENDENCY_FIELDS:
        for dep_name, spec in (root_entry.get(field_name) or {}).items():
            target = by_path.get(resolve_install_path("", dep_name, lock["packages"]))
            if target is None:
                unresolved.append(dep_name)
                continue
            depends_on(root_id, dep_name, spec, dep_type, target)
    for dep in deps:
        if dep.target is not None:
            depends_on(version_id(dep.source.name, dep.source.version), dep.dep_name, dep.spec,
                       dep.dependency_type, dep.target)
        elif dep.dependency_type == "prod":
            unresolved.append(f"{dep.dep_name} (for {dep.source.name}@{dep.source.version})")

    advisories: dict[str, dict] = {}
    for vid in install_paths:
        pkg_name, pkg_version = vid.removeprefix("npm:").rsplit("@", 1)
        if pkg_name not in advisories:
            advisories[pkg_name] = package_advisories(base, pkg_name)
        for vuln_id, ranges in advisories[pkg_name].items():
            if _affected(pkg_version, ranges):
                store.upsert_edge({
                    "subject_id": vid, "relation": "HAS_VULNERABILITY", "object_id": vuln_id,
                    "provenance": [{"source_doc_id": vuln_id, "source_url": OSV_WEB + vuln_id,
                                    "extraction_method": "derived", "confidence": 1.0}],
                    "properties": {"lockfile_doc_ids": [doc_id]},
                })

    unchecked = sorted(vid.removeprefix("npm:") for vid in install_paths
                       if not (base.get_entity(vid) or {}).get("properties", {}).get("in_tree"))
    upload = Upload(doc_id, root_id, name, version, store, install_paths, dev_only, unchecked)
    workspaces = sorted(p for p in lock["packages"] if p and NODE_MODULES not in p)
    if workspaces:
        upload.warnings.append(f"workspace packages are not scanned, only the root project's dependencies: "
                               f"{', '.join(workspaces[:10])}")
    if unresolved:
        upload.warnings.append(f"{len(unresolved)} declared dependencies are not installed in the lockfile "
                               f"(e.g. {', '.join(unresolved[:5])}); their subtrees are not scanned")
    if unchecked:
        upload.warnings.append(f"{len(unchecked)} of {len(install_paths)} installed versions are outside this "
                               f"dataset, so OSV was never queried for them; they are matched only against the "
                               f"advisories already held for their package, and others may exist")
    return upload
