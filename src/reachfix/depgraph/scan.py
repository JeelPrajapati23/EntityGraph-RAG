"""Scan an uploaded package-lock.json: exposure plus a fix plan per vulnerable copy.

The upload is layered over the corpus graph (npm/upload.py), then the same
exposure walk and remediation planner the router uses run on it. Rows have
the router's exposure / remediation row shapes, so api/views.py can draw
them.
"""

from dataclasses import replace
from typing import Protocol

from ..graph.exposure import exposure
from ..npm.releases import Releases
from ..npm.remediation import actions, is_resolved, plan_fix
from ..npm.upload import Upload
from .dispatch import (MAX_PLANS, MAX_ROWS, DepGraphContext, advisory_row, by_severity, exposure_totals, fixed_in,
                       package_of, remediation_totals)


MAX_FETCH_ROUNDS = 10    # an upgrade chain climbs one dependent per round, like scripts/fetch_release_metadata.py
MAX_FETCHED = 300        # packages fetched per scan, so one huge lockfile can't hammer the registry


class ReleaseFetcher(Protocol):
    """npm.live_releases.RegistryClient, or a fake in tests."""

    def fetch(self, names) -> tuple[dict[str, dict], dict[str, str]]: ...


def no_metadata_row(ctx: DepGraphContext, upload: Upload, version_id: str, rows: list[dict]) -> dict:
    """Without its version list the planner would claim nothing is fixed, so give the advisories' fixes instead."""
    name = package_of(version_id)
    advisories = sorted({r["vulnerability_id"] for r in rows if r["version_id"] == version_id})
    fixes = sorted({v.removeprefix("npm:") for a in advisories for v in fixed_in(ctx, a, name)})
    return {"plan": {"version_id": version_id, "package": name, "status": "no_metadata"},
            "advisories": [advisory_row(ctx, a) for a in advisories],
            "actions": [f"No release metadata for {name}, so no upgrade plan. The advisories list these fixed "
                        f"versions: {', '.join(fixes) or 'none'}. Pick a release at or above the fix for each "
                        f"advisory."],
            "resolved": False, "incomplete": [name]}


def plan_rows(ctx: DepGraphContext, upload: Upload, releases: Releases, targets: list[tuple[str, dict]],
              rows: list[dict]) -> list[dict]:
    plans = []
    for version_id, row in targets:
        base = {"project": upload.root_id, "lockfile_doc_id": upload.lockfile_doc_id, "version_id": version_id,
                "path": row["path"], "depth": row["depth"], "dev_only": row["dev_only"]}
        if package_of(version_id) not in releases.packages:
            releases.missing.add(package_of(version_id))
            plans.append({**base, **no_metadata_row(ctx, upload, version_id, rows)})
            continue
        missing_before = set(releases.missing)
        plan = plan_fix(upload.store, releases, upload.lockfile_doc_id, version_id, project_root=upload.root_id)
        steps = actions(plan)
        incomplete = sorted(releases.missing - missing_before)
        if incomplete:
            steps.insert(0, f"Release metadata for {', '.join(incomplete)} is missing, so this plan may miss "
                            f"fixed versions or upgrade paths.")
        plans.append({**base, "advisories": [advisory_row(ctx, a) for a in plan["advisories"]], "plan": plan,
                      "actions": steps, "resolved": is_resolved(plan) and not incomplete, "incomplete": incomplete})
    return plans


def plan_upload(ctx: DepGraphContext, upload: Upload, rows: list[dict], max_plans: int,
                registry: ReleaseFetcher | None = None) -> tuple[dict, list[str]]:
    """Fix plans for the worst `max_plans` vulnerable copies (rows arrive worst severity first).

    With a registry, each round fetches the release metadata the plans
    found missing and plans again, until nothing new is missing.
    """
    first_row: dict[str, dict] = {}
    for row in rows:
        first_row.setdefault(row["version_id"], row)
    targets = list(first_row.items())[:max_plans]
    packages = dict(ctx.releases.packages)  # a copy: fetched packages must not leak into the shared context
    fetched: set[str] = set()
    failed: dict[str, str] = {}
    for _ in range(MAX_FETCH_ROUNDS + 1):
        releases = Releases(packages)
        plans = plan_rows(ctx, upload, releases, targets, rows)
        todo = sorted(releases.missing - fetched - set(failed))[:MAX_FETCHED - len(fetched) - len(failed)]
        if registry is None or not todo:
            break
        got, errors = registry.fetch(todo)
        packages.update(got)
        fetched.update(got)
        failed.update(errors)

    totals = {**remediation_totals(plans), "vulnerable_copies": len(first_row),
              "incomplete": sum(bool(p["incomplete"]) for p in plans), "releases_fetched": len(fetched)}
    warnings = []
    if len(first_row) > max_plans:
        warnings.append(f"planned fixes for the {max_plans} worst of {len(first_row)} vulnerable copies")
    if failed:
        warnings.append(f"registry fetch failed for {len(failed)} packages (e.g. "
                        f"{'; '.join(f'{n}: {e}' for n, e in sorted(failed.items())[:3])})")
    if releases.missing:
        warnings.append(f"release metadata missing for {len(releases.missing)} packages "
                        f"(e.g. {', '.join(sorted(releases.missing)[:5])}); plans touching them may be incomplete")
    return {"results": plans, "total_results": len(plans), "totals": totals}, warnings


def run_scan(ctx: DepGraphContext, upload: Upload, *, max_plans: int = MAX_PLANS,
             registry: ReleaseFetcher | None = None) -> dict:
    """Exposure and remediation for one uploaded lockfile (built by npm.upload.load_upload over ctx.store).

    With a registry, release metadata the plans need but releases.json lacks is fetched live.
    """
    uctx = replace(ctx, store=upload.store)
    rows = []
    for hit in exposure(upload.store, upload.root_id, upload.lockfile_doc_id):
        rows.append({"project": upload.root_id, "lockfile_doc_id": upload.lockfile_doc_id, **hit,
                     **advisory_row(uctx, hit["vulnerability_id"]),
                     "fixed_in": fixed_in(uctx, hit["vulnerability_id"], package_of(hit["version_id"])),
                     "dev_only": hit["version_id"] in upload.dev_only})
    rows.sort(key=by_severity)

    warnings = list(upload.warnings)
    if ctx.releases is None:
        remediation = None
        warnings.append("no release metadata loaded, so no fix plans; run scripts/build_remediation.py")
    else:
        remediation, plan_warnings = plan_upload(uctx, upload, rows, max_plans, registry)
        warnings.extend(plan_warnings)

    totals = exposure_totals(rows).get(upload.root_id, {"advisories": 0, "vulnerable_versions": 0,
                                                        "by_severity": {}, "max_depth": 0})
    totals["dev_only_advisories"] = len({r["vulnerability_id"] for r in rows if r["dev_only"]}
                                        - {r["vulnerability_id"] for r in rows if not r["dev_only"]})
    return {
        "executed_route": "relational", "pattern": "scan", "executed_pattern": "scan",
        "project": {"id": upload.root_id, "name": upload.name, "version": upload.version},
        "lockfile_doc_id": upload.lockfile_doc_id, "coverage": upload.coverage(),
        "results": rows[:MAX_ROWS], "total_results": len(rows), "totals": totals,
        "remediation": remediation, "warnings": warnings,
    }
