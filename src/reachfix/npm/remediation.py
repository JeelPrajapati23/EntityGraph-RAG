"""Remediation plans: the smallest upgrade that removes a vulnerable version from one lockfile (Phase 9).

For a vulnerable copy name@current in a lockfile:

1. Safe versions: published, stable, newer than current, and outside every
   target advisory's OSV ranges. Targets are the advisories on that copy
   (or the ones asked about), plus every advisory on the package sharing a
   CVE with one of them, so an incomplete fix and its follow-up are fixed
   together (the highest fix wins). Safe versions are ranked: clear of
   every known advisory on the package first, then not deprecated, then
   lowest.
2. The copy's dependents in this lockfile (DEPENDS_ON in-edges carrying
   this lockfile) each declare a range. Status:
   - in_range: one safe version satisfies every range, so refreshing the
     lockfile (`npm update <name>`) fixes it with no manifest change;
   - split: every range admits some safe version, but no single one does,
     so npm installs a separate copy per dependent;
   - blocked: some range admits no safe version (e.g. mocha@8.4.0 pins
     minimatch to exactly "3.0.4");
   - upgrade_root: the vulnerable copy is the lockfile's root project;
   - no_fix: no published version is safe.
3. For each blocking dependent, the same question one level up: the lowest
   newer version of the dependent whose declared range admits a safe
   version (or that no longer declares the dependency), checked against
   the dependent's own dependents. Versions admitting one of the child's
   best-ranked safe versions come first, so the preference in step 1
   carries up the chain. This repeats up to the root. It is a
   greedy walk, one chain at a time, not a solver over the whole tree
   (see the plan's future improvements). An npm `overrides` entry is always
   given as the fallback, with a flag when it forces a version outside a
   declared range.

For an uploaded lockfile the root is the user's own project, not a registry
package, so it is never upgraded: a range it declares that blocks every fix
becomes an `edit_manifest` step (change that range in package.json), or
`remove_dependency` when no version of the dependency is fixed.

"Safe" means safe against the advisories in this dataset. They were fetched
for corpus versions, so an advisory affecting only newer versions may be
missing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from ..graph.exposure import DEPENDS_ON, HAS_VULNERABILITY
from ..graph.store import GraphStore
from .graph_load import root_of_lockfile
from .releases import Releases
from .versions import compare, is_affected, satisfies
from .vulnerabilities import package_id

MAX_UPGRADE_DEPTH = 25  # jest 26's exactly-pinned packages chain ~15 deep before reaching the root


def split_version_id(node_id: str) -> tuple[str, str]:
    """"npm:@babel/core@7.0.0" -> ("@babel/core", "7.0.0")."""
    name, _, version = node_id.removeprefix("npm:").rpartition("@")
    return name, version


def dependents(store: GraphStore, node_id: str, lockfile_doc_id: str) -> list[dict]:
    """Who depends on this copy in this lockfile, with the range each declares."""
    rows = []
    for edge in store.neighbors(node_id, relation=DEPENDS_ON, direction="in"):
        props = edge["properties"]
        if lockfile_doc_id in props.get("lockfile_doc_ids", ()):
            rows.append({"dependent": edge["entity_id"], "dep_name": props.get("dep_name"),
                         "range": props.get("version_range"), "dependency_type": props.get("dependency_type")})
    return sorted(rows, key=lambda r: r["dependent"])


def package_advisories(store: GraphStore, name: str) -> dict[str, dict]:
    """advisory id -> its merged OSV ranges for this package, withdrawn advisories left out."""
    found = {}
    for edge in store.neighbors(package_id(name), relation="AFFECTS_VERSION_RANGE", direction="in"):
        vuln = store.get_entity(edge["entity_id"]) or {}
        if vuln.get("properties", {}).get("withdrawn_at"):
            continue
        found[edge["entity_id"]] = {"ranges": edge["properties"].get("ranges", []),
                                    "versions": edge["properties"].get("versions", [])}
    return found


def cves(store: GraphStore, vuln_id: str) -> set[str]:
    aliases = (store.get_entity(vuln_id) or {}).get("properties", {}).get("aliases", [])
    return {a.upper() for a in aliases if a.upper().startswith("CVE-")}


def with_shared_cves(store: GraphStore, targets: set[str], known: set[str]) -> set[str]:
    """Targets plus every known advisory sharing a CVE with one of them."""
    shared = set().union(*(cves(store, t) for t in targets)) if targets else set()
    return targets | {a for a in known if cves(store, a) & shared}


def satisfies_range(version: str, version_range: str | None) -> bool:
    return version_range is not None and satisfies(version, version_range)


@dataclass
class _Env:
    store: GraphStore
    releases: Releases
    lockfile_doc_id: str
    root: str
    editable_root: bool = False  # the root is a local project whose package.json is edited (an upload)
    # (dependent, dependency name, child candidates, best of them) -> plan. Blockers repeat across branches,
    # e.g. jest's packages pin each other exactly and all lead back to jest-config.
    memo: dict = field(default_factory=dict)


def top_tier(ranked: list[str], key: Callable[[str], tuple]) -> frozenset:
    """The candidates tied with the first one under the ranking key."""
    return frozenset(v for v in ranked if key(v) == key(ranked[0])) if ranked else frozenset()


def plan_copy(env: _Env, node_id: str, candidates: list[str], describe: Callable[[str], dict] | None = None,
              depth: int = 0, seen: frozenset = frozenset(), best: frozenset | None = None) -> dict:
    """Plan for one copy, given its acceptable versions in preference order and the best-ranked of them.

    describe(version), if given, annotates each version the plan picks
    (e.g. what that version declares for the dependency below it). With no
    candidates the copy can't be fixed in place, but a dependent may still
    be upgraded to a release that no longer depends on it.
    """
    name, current = split_version_id(node_id)
    step = {"version_id": node_id, "package": name, "current_version": current, "candidates": len(candidates)}
    note = describe or (lambda v: {})
    if node_id == env.root:
        if not candidates:
            return {**step, "status": "no_fix"}
        return {**step, "status": "upgrade_root", "target_version": candidates[0], **note(candidates[0])}

    deps = dependents(env.store, node_id, env.lockfile_doc_id)
    for d in deps:
        d["admits"] = next((c for c in candidates if satisfies_range(c, d["range"])), None)
    step["dependents"] = deps
    shared = next((c for c in candidates if all(satisfies_range(c, d["range"]) for d in deps)), None)
    if shared is not None:
        return {**step, "status": "in_range", "target_version": shared, **note(shared)}

    blocked = [d for d in deps if d["admits"] is None]
    for d in deps:
        if d["admits"] is not None:
            d.update(note(d["admits"]))
    if candidates and not blocked:
        return {**step, "status": "split"}

    for d in blocked:
        if d["dependent"] in seen:
            d["upgrade"] = {"status": "cycle"}  # already being upgraded further down this chain
        elif depth + 1 > MAX_UPGRADE_DEPTH:
            d["upgrade"] = {"status": "too_deep"}
        else:
            d["upgrade"] = upgrade_dependent(env, d, candidates, best if best is not None else frozenset(candidates),
                                             depth + 1, seen | {node_id})
    if not candidates:
        return {**step, "status": "no_fix"}
    override = candidates[0]
    return {**step, "status": "blocked", "target_version": override, **note(override),
            "override": {"package": name, "version": override,
                         "outside_ranges": [d["dependent"] for d in deps if not satisfies_range(override, d["range"])]}}


def upgrade_dependent(env: _Env, dependent: dict, child_candidates: list[str], child_best: frozenset,
                      depth: int, seen: frozenset) -> dict:
    """Plan the lowest upgrade of a blocking dependent whose declared range lets the child be fixed (or drops it)."""
    parent_id, dep_name = dependent["dependent"], dependent["dep_name"]
    memo_key = (parent_id, dep_name, tuple(child_candidates), child_best)
    if memo_key in env.memo:
        return env.memo[memo_key]
    if env.editable_root and parent_id == env.root:
        return edit_manifest(dependent, child_candidates)
    name, current = split_version_id(parent_id)
    # spec -> (admits a safe child version, admits a best-ranked one). No spec: the dependency is dropped.
    admits: dict[str | None, tuple[bool, bool]] = {None: (True, True)}
    declared: dict[str, str | None] = {}
    for version in env.releases.stable_versions(name):
        if compare(version, current) <= 0:
            continue
        manifest = env.releases.manifest(name, version)
        if manifest is None:
            continue  # unknown; recorded in releases.missing
        spec = manifest["dependencies"].get(dep_name)
        if spec not in admits:
            fits = [c for c in child_candidates if satisfies(c, spec)]
            admits[spec] = (bool(fits), any(c in child_best for c in fits))
        if admits[spec][0]:
            declared[version] = spec

    def rank(v: str) -> tuple:
        return (not admits[declared[v]][1], env.releases.deprecated(name, v))

    ranked = sorted(declared, key=rank)  # stable: keeps version order within a tier

    def describe(version: str) -> dict:
        spec = declared[version]
        return {"declares": {dep_name: spec}} if spec is not None else {"drops_dependency": dep_name}

    env.memo[memo_key] = plan_copy(env, parent_id, ranked, describe, depth, seen, top_tier(ranked, rank))
    return env.memo[memo_key]


def edit_manifest(dependent: dict, child_candidates: list[str]) -> dict:
    """The local project's own range blocks every fix: change it to admit the best-ranked fixed version."""
    step = {"version_id": dependent["dependent"], "dep_name": dependent["dep_name"],
            "current_range": dependent["range"], "dependency_type": dependent["dependency_type"]}
    if not child_candidates:
        return {**step, "status": "remove_dependency"}
    target = child_candidates[0]
    return {**step, "status": "edit_manifest", "target_version": target, "suggested_range": f"^{target}"}


def is_resolved(plan: dict) -> bool:
    """Whether the plan fixes the copy without an override: in place, or by upgrading every blocking dependent.

    A blocker that is already being upgraded lower in the same chain (a
    mutual constraint, e.g. webpack <-> terser-webpack-plugin's peer range) is
    assumed to move with that upgrade; summarize() lists those as unchecked.
    """
    if plan["status"] in ("in_range", "split", "upgrade_root", "edit_manifest", "cycle"):
        return True  # a cycle is counted here and listed as unchecked by summarize()
    blocked = [d for d in plan.get("dependents", []) if d["admits"] is None]
    return bool(blocked) and all(is_resolved(d["upgrade"]) for d in blocked)


def plan_fix(store: GraphStore, releases: Releases, lockfile_doc_id: str, node_id: str,
             vulnerability_ids: set[str] | None = None, project_root: str | None = None) -> dict:
    """Remediation plan for one vulnerable copy in one lockfile.

    vulnerability_ids limits the targets to those advisories; by default
    every advisory on the copy is a target. project_root is the root node of
    an uploaded lockfile (a local project, edited rather than upgraded); by
    default the root is the corpus package the lockfile was resolved for.
    """
    name, current = split_version_id(node_id)
    known = package_advisories(store, name)
    on_copy = {e["entity_id"] for e in store.neighbors(node_id, relation=HAS_VULNERABILITY, direction="out")}
    targets = on_copy & vulnerability_ids if vulnerability_ids is not None else on_copy
    targets = with_shared_cves(store, targets, set(known)) & set(known)

    releases.require_complete(name)
    safe = [v for v in releases.stable_versions(name)
            if compare(v, current) > 0 and not any(is_affected(v, known[t]) for t in targets)]
    others = {v: sorted(a for a in known if a not in targets and is_affected(v, known[a])) for v in safe}

    def rank(v: str) -> tuple:
        return (bool(others[v]), releases.deprecated(name, v))

    ranked = sorted(safe, key=rank)

    def describe(version: str) -> dict:
        return {"still_affected_by": others[version]} if others[version] else {}

    env = _Env(store, releases, lockfile_doc_id, root=project_root or root_of_lockfile(lockfile_doc_id),
               editable_root=project_root is not None)
    plan = plan_copy(env, node_id, ranked, describe, best=top_tier(ranked, rank))
    return {"lockfile_doc_id": lockfile_doc_id, "advisories": sorted(targets),
            "lowest_safe_version": safe[0] if safe else None,
            "lowest_safe_still_affected_by": others[safe[0]] if safe else [], **plan}


MAX_LISTED = 8


def _blocked(plan: dict) -> list[dict]:
    return [d for d in plan.get("dependents", []) if d["admits"] is None]


def _why(plan: dict, dep_name: str) -> str:
    if plan.get("drops_dependency"):
        return f"drops {plan['drops_dependency']}"
    return f"declares {dep_name} \"{plan['declares'][dep_name]}\"" if plan.get("declares") else ""


def summarize(plan: dict) -> dict:
    """A blocked / no_fix plan's upgrade tree, flattened and merged across chains.

    - root: the project upgrade(s) every chain ends in;
    - manifest: for an uploaded project, ranges in its own package.json to
      change, dep name -> {from, to, version};
    - refresh: dependents whose fixed version already fits every range
      declared for them, so a lockfile refresh picks them up;
    - via: intermediate upgrades that come with the ones above, as the
      lowest version that works; the upgraded root may require a higher one;
    - unchecked: mutual constraints (a blocker already being upgraded lower
      in the same chain), assumed to move together;
    - unresolved: blockers with no upgrade path, with the reason.
    Each upgrade maps package -> {version, from, whys}. If chains pick
    different versions, the higher is kept.
    """
    out = {"root": {}, "manifest": {}, "refresh": {}, "via": {}, "unchecked": [], "unresolved": []}

    def add(bucket: str, up: dict, why: str) -> None:
        name, version = up["package"], up["target_version"]
        have = out[bucket].setdefault(name, {"version": version, "from": up["current_version"], "whys": set()})
        if compare(version, have["version"]) > 0:
            have["version"] = version
        if why:
            have["whys"].add(why)

    def walk(p: dict) -> None:
        for d in _blocked(p):
            up, who = d["upgrade"], d["dependent"].removeprefix("npm:")
            if up["status"] == "cycle":
                out["unchecked"].append(f"{who} declares {p['package']} \"{d['range']}\"")
            elif up["status"] == "edit_manifest":
                have = out["manifest"].get(up["dep_name"])
                if have is None or compare(up["target_version"], have["version"]) > 0:
                    out["manifest"][up["dep_name"]] = {"from": up["current_range"], "to": up["suggested_range"],
                                                       "version": up["target_version"]}
            elif up["status"] == "remove_dependency":
                out["unresolved"].append(f"the project declares {p['package']} \"{d['range']}\" directly, and no "
                                         f"known release of it is fixed; remove or replace it")
            elif up["status"] == "too_deep":
                out["unresolved"].append(f"{who} declares {p['package']} \"{d['range']}\"; the upgrade chain is "
                                         f"longer than {MAX_UPGRADE_DEPTH} steps and was not followed")
            elif up["status"] == "no_fix" and not up.get("dependents"):
                out["unresolved"].append(f"{who} declares {p['package']} \"{d['range']}\", and no newer "
                                         f"{up['package']} release admits a fixed version or drops it")
            elif up["status"] == "no_fix":
                walk(up)  # can't upgrade it, but its own dependents may drop it
            else:
                why = _why(up, d["dep_name"])
                if up["status"] == "upgrade_root":
                    add("root", up, why)
                elif up["status"] in ("in_range", "split"):
                    add("refresh", up, why)
                else:
                    add("via", up, why)
                    walk(up)

    walk(plan)
    for bucket in ("refresh", "via"):  # a package upgraded as the project root is listed there only
        for name in out["root"]:
            out[bucket].pop(name, None)
    out["unchecked"] = sorted(set(out["unchecked"]))
    out["unresolved"] = sorted(set(out["unresolved"]))
    return out


MAX_WHYS = 3


def _listed(upgrades: dict, at_least: bool = False) -> str:
    """Upgrades as text, with the reasons the chains give (omitted when there are many)."""
    items = [f"{name} {u['from']} -> {'>= ' if at_least else ''}{u['version']}"
             + (f" ({'; '.join(sorted(u['whys']))})" if 0 < len(u["whys"]) <= MAX_WHYS else "")
             for name, u in sorted(upgrades.items())]
    more = f", and {len(items) - MAX_LISTED} more" if len(items) > MAX_LISTED else ""
    return "; ".join(items[:MAX_LISTED]) + more


def _capped(items: list[str], sep: str = "; ") -> str:
    more = f"{sep}and {len(items) - MAX_LISTED} more" if len(items) > MAX_LISTED else ""
    return sep.join(items[:MAX_LISTED]) + more


def actions(plan: dict) -> list[str]:
    """The plan as short, ordered, human-readable steps (used for graph facts and the CLI)."""
    name, status = plan["package"], plan["status"]
    target = plan.get("target_version")
    if status == "upgrade_root":
        return [f"Upgrade {name} itself from {plan['current_version']} to {target}."]
    if status == "in_range":
        return [f"Refresh the lockfile (`npm update {name}`): {name}@{target} satisfies every dependent's declared range."]
    if status == "split":
        return ["Refresh the lockfile: no single version fits every dependent, so npm installs separate copies: "
                + "; ".join(f"{name}@{d['admits']} for {d['dependent'].removeprefix('npm:')} ({d['range']})"
                            for d in plan["dependents"]) + "."]
    if status == "no_fix" and not plan.get("dependents"):
        return [f"No published version of {name} newer than {plan['current_version']} is outside the advisory ranges."]

    blockers = _capped([f"{d['dependent'].removeprefix('npm:')} (declares {name} \"{d['range']}\")"
                         for d in _blocked(plan)], ", ")
    if status == "no_fix":
        steps = [f"No published version of {name} newer than {plan['current_version']} is outside the advisory "
                 f"ranges; it can only be removed, by upgrading what depends on it: {blockers}."]
    else:
        steps = [f"{name}@{target} is the lowest preferred fixed version, but these dependents' declared ranges "
                 f"exclude every fixed version: {blockers}."]
    s = summarize(plan)
    if s["manifest"]:
        steps.append("Edit the project's package.json, then reinstall: "
                     + _capped([f"{dep} \"{m['from']}\" -> \"{m['to']}\"" for dep, m in sorted(s["manifest"].items())])
                     + ".")
    if s["root"]:
        lead = "Upgrade the project" if not s["unresolved"] else "Upgrading the project clears only some blockers"
        steps.append(f"{lead}: {_listed(s['root'])}.")
    if s["refresh"]:
        steps.append(f"Refresh the lockfile to take: {_listed(s['refresh'])}; each new version fits the ranges "
                     f"its own dependents declare, so no manifest changes.")
    if s["via"]:
        steps.append(f"Those upgrades bring in: {_listed(s['via'], at_least=True)}.")
    if s["unchecked"]:
        steps.append(f"Assumed to move together, not checked (each is being upgraded in the same chain): "
                     f"{_capped(s['unchecked'])}.")
    if s["unresolved"]:
        steps.append(f"No upgrade path for: {_capped(s['unresolved'])}.")
    fine = [d for d in plan.get("dependents", []) if d["admits"] is not None]
    if fine:
        steps.append("The other dependents already accept a fixed version after a lockfile refresh: "
                     + _capped([f"{d['dependent'].removeprefix('npm:')} (declares {name} \"{d['range']}\") "
                                f"-> {name}@{d['admits']}" for d in fine]) + ".")
    if status == "blocked":
        override = plan["override"]
        outside = _capped([v.removeprefix("npm:") for v in override["outside_ranges"]], ", ")
        steps.append(f"Fallback: `\"overrides\": {{\"{name}\": \"{override['version']}\"}}` in package.json forces "
                     f"{name}@{override['version']} outside the range declared by {outside}; test before relying on it.")
    return steps


def vulnerable_copies(vulnerability_edges: list[dict]) -> list[tuple[str, str]]:
    """Every (lockfile doc id, vulnerable version id) pair, from vulnerability_edges.jsonl rows."""
    return sorted({(doc_id, row["subject"]) for row in vulnerability_edges if row["relation"] == HAS_VULNERABILITY
                   for doc_id in row["lockfile_doc_ids"]})
