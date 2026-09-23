"""Scan an uploaded package-lock.json: exposure plus a fix plan per vulnerable copy.

The upload is layered over the corpus graph (npm/upload.py), then the same
exposure walk and remediation planner the router uses run on it. Rows have
the router's exposure / remediation row shapes, so api/views.py can draw
them.
"""

from dataclasses import replace

from ..graph.exposure import exposure
from ..npm.releases import Releases
from ..npm.remediation import actions, is_resolved, plan_fix
from ..npm.upload import Upload
from .dispatch import (MAX_PLANS, MAX_ROWS, DepGraphContext, advisory_row, by_severity, exposure_totals, fixed_in,
                       package_of, remediation_totals)


def plan_upload(ctx: DepGraphContext, upload: Upload, rows: list[dict], max_plans: int) -> tuple[dict, list[str]]:
    """Fix plans for the worst `max_plans` vulnerable copies (rows arrive worst severity first)."""
    first_row: dict[str, dict] = {}
    for row in rows:
        first_row.setdefault(row["version_id"], row)
    releases = Releases(ctx.releases.packages)  # fresh missing/touched sets, so concurrent scans don't share them
    plans = []
    for version_id, row in list(first_row.items())[:max_plans]:
        missing_before = set(releases.missing)
        plan = plan_fix(upload.store, releases, upload.lockfile_doc_id, version_id, project_root=upload.root_id)
        steps = actions(plan)
        incomplete = sorted(releases.missing - missing_before)
        if incomplete:
            steps.insert(0, f"Release metadata for {', '.join(incomplete)} is not in this dataset, so this plan "
                            f"may miss fixed versions or upgrade paths.")
        plans.append({"project": upload.root_id, "lockfile_doc_id": upload.lockfile_doc_id, "version_id": version_id,
                      "path": row["path"], "depth": row["depth"], "dev_only": row["dev_only"],
                      "advisories": [advisory_row(ctx, a) for a in plan["advisories"]], "plan": plan,
                      "actions": steps, "resolved": is_resolved(plan) and not incomplete,
                      "incomplete": incomplete})
    totals = {**remediation_totals(plans), "vulnerable_copies": len(first_row),
              "incomplete": sum(bool(p["incomplete"]) for p in plans)}
    warnings = []
    if len(first_row) > max_plans:
        warnings.append(f"planned fixes for the {max_plans} worst of {len(first_row)} vulnerable copies")
    if releases.missing:
        warnings.append(f"release metadata missing for {len(releases.missing)} packages "
                        f"(e.g. {', '.join(sorted(releases.missing)[:5])}); plans touching them may be incomplete")
    return {"results": plans, "total_results": len(plans), "totals": totals}, warnings


def run_scan(ctx: DepGraphContext, upload: Upload, *, max_plans: int = MAX_PLANS) -> dict:
    """Exposure and remediation for one uploaded lockfile (built by npm.upload.load_upload over ctx.store)."""
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
        remediation, plan_warnings = plan_upload(uctx, upload, rows, max_plans)
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
