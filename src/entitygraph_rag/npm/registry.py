"""Trim a full npm registry packument down to what schema v2 needs.

Full packuments can be many MB (every version's full manifest and README).
Only a small slice is kept on disk: maintainer usernames, publish times,
the version list, and license/deprecation/dependencies for the versions
that actually appear in a corpus tree.
"""

from urllib.parse import quote

REGISTRY_URL = "https://registry.npmjs.org/"


def packument_url(name: str) -> str:
    # Scoped names keep the "@" but escape the "/": @babel/core -> @babel%2Fcore
    return REGISTRY_URL + quote(name, safe="@")


def maintainer_usernames(maintainers: list | None) -> list[str]:
    """Usernames only. Emails are dropped on purpose (see schema/v2.yaml, Maintainer)."""
    names = []
    for m in maintainers or []:
        if isinstance(m, dict):
            name = m.get("name")
        else:  # old-style "name <email>" strings
            name = str(m).split("<", 1)[0].strip()
        if name:
            names.append(name)
    return sorted(set(names))


def normalize_license(manifest: dict) -> str | None:
    """Collapse the registry's historical license shapes into one string.

    Seen in the wild: "MIT", {"type": "MIT", "url": ...}, and a legacy
    `licenses: [{"type": ...}, ...]` array (joined with " OR ").
    """
    lic = manifest.get("license")
    if isinstance(lic, str):
        return lic.strip() or None
    if isinstance(lic, dict):
        return lic.get("type")
    legacy = manifest.get("licenses")
    if isinstance(legacy, list):
        types = [x.get("type") if isinstance(x, dict) else str(x) for x in legacy]
        types = [t for t in types if t]
        return " OR ".join(types) or None
    return None


def trim_packument(packument: dict, wanted_versions: set[str]) -> dict:
    versions = packument.get("versions", {})
    kept = {}
    for version in sorted(wanted_versions):
        manifest = versions.get(version)
        if manifest is None:
            kept[version] = {"missing": True}  # e.g. unpublished since the tree was resolved
            continue
        kept[version] = {
            "license": normalize_license(manifest),
            "deprecated": manifest.get("deprecated") or None,
            "dependencies": manifest.get("dependencies", {}),
            "optionalDependencies": manifest.get("optionalDependencies", {}),
            "peerDependencies": manifest.get("peerDependencies", {}),
        }

    return {
        "name": packument["name"],
        "maintainers": maintainer_usernames(packument.get("maintainers")),
        "dist_tags": packument.get("dist-tags", {}),
        "time": packument.get("time", {}),
        "all_versions": list(versions),
        "versions": kept,
    }


def declared_dependencies(version_meta: dict) -> dict[str, dict[str, str]]:
    """A trimmed version's declared deps, split by type the way a lockfile splits them.

    The registry manifest lists optional deps under both `dependencies` and
    `optionalDependencies`. A lockfile lists them only under
    `optionalDependencies`, so they are removed from "prod" here.
    """
    optional = version_meta.get("optionalDependencies", {})
    return {
        "prod": {k: v for k, v in version_meta.get("dependencies", {}).items() if k not in optional},
        "optional": dict(optional),
        "peer": dict(version_meta.get("peerDependencies", {})),
    }


def trim_releases(packument: dict) -> dict:
    """Every version's declared dependencies and deprecation, for remediation (Phase 9).

    trim_packument keeps manifests only for corpus versions. Remediation
    also has to ask what a *newer* version of a package declares ("does
    glob 8 still pin minimatch to ^3?"), so this keeps that slice for all
    versions. It is fetched only for the packages remediation asks about.
    """
    return {
        "name": packument["name"],
        "versions": {
            version: {"dependencies": {dep: spec for deps in declared_dependencies(manifest).values()
                                       for dep, spec in deps.items()},
                      "deprecated": manifest.get("deprecated") or None}
            for version, manifest in packument.get("versions", {}).items()
        },
    }
