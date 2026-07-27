#!/usr/bin/env python3
"""Aggregate and treatment-vs-control movement for the contract's metrics.

This tool answers "what changed, by how much, on how much data" — and nothing
else. It does not interpret, rank, or explain. That separation is the point: the
model receives arithmetic it can rely on and spends its judgment on what the
arithmetic means.

Two numbers matter more than the headline:

- `treatment_vs_control_relative_pct` — the only movement that can be attributed
  to a feature shipped to one arm. A pre/post change that shows up in both arms
  is something else happening in the world.
- `exceeds_mde` — whether the movement clears the minimum detectable effect from
  the launch contract. Below it, the honest answer is "we cannot tell yet".

Usage:
    python3 src/tools/metric_movement.py --checkpoint 30
    python3 src/tools/metric_movement.py --metric subscription_conversion_rate
"""

from __future__ import annotations

import sys

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli, _store, _windows, metric_definitions
else:
    from . import _cli, _store, _windows, metric_definitions


def contract_metrics(brief: dict) -> list[dict]:
    """Every metric the contract obliges us to report on, tagged by its role."""
    metrics = [{"metric": brief["primary_outcome"]["metric"], "role": "primary"}]
    for entry in brief.get("secondary_metrics", []):
        metrics.append({"metric": entry["metric"], "role": "secondary"})
    for entry in brief.get("guardrail_metrics", []):
        metrics.append({"metric": entry["metric"], "role": "guardrail"})
    seen = set()
    ordered = []
    for entry in metrics:
        if entry["metric"] in seen:
            continue
        seen.add(entry["metric"])
        ordered.append(entry)
    return ordered


def movement_for(conn, brief: dict, window, metric: str, role: str) -> dict:
    definition = metric_definitions.get(metric)
    mde = brief["primary_outcome"].get("minimum_detectable_effect_pct")

    def one(start: str, end: str, filters: dict | None = None) -> dict:
        rows = _store.rate(conn, metric, start, end, filters=filters)
        row = rows[0] if rows else {}
        return {
            "value": _store.round_or_none(row.get("value")),
            "numerator": row.get("numerator"),
            "denominator": row.get("denominator"),
        }

    pre_all = one(window.pre_start, window.pre_end)
    post_all = one(window.post_start, window.post_end)
    post_treatment = one(window.post_start, window.post_end, {"assignment": "treatment"})
    post_control = one(window.post_start, window.post_end, {"assignment": "control"})
    pre_treatment = one(window.pre_start, window.pre_end, {"assignment": "treatment"})
    pre_control = one(window.pre_start, window.pre_end, {"assignment": "control"})

    pre_post_pct = _store.relative_change_pct(pre_all["value"], post_all["value"])
    arm_pct = _store.relative_change_pct(post_control["value"], post_treatment["value"])

    # Difference-in-differences: strips out any pre-existing arm imbalance.
    pre_arm_pct = _store.relative_change_pct(pre_control["value"], pre_treatment["value"])
    did_pct = None
    if arm_pct is not None and pre_arm_pct is not None:
        did_pct = round(arm_pct - pre_arm_pct, 4)

    warnings: list[str] = []
    if post_all["denominator"] in (None, 0):
        warnings.append(f"No data for {metric} in the checkpoint window.")
    if definition is None:
        warnings.append(
            f"{metric} has no governed definition in src/tools/metric_definitions.py. "
            f"Do not report it without one."
        )
    if pre_all["value"] in (None, 0) and post_all["value"] not in (None, 0):
        warnings.append(
            f"{metric} has no pre-period baseline, so no pre/post comparison is "
            f"possible. Compare arms instead."
        )

    exceeds_mde = None
    if did_pct is not None and mde is not None:
        exceeds_mde = abs(did_pct) >= mde

    return {
        "metric": metric,
        "role": role,
        "evidence_id": _cli.evidence_id("MOV", metric, f"d{window.checkpoint_days}"),
        "definition_version": (definition or {}).get("version"),
        "depends_on_events": (definition or {}).get("depends_on_events", []),
        "pre_period": pre_all,
        "checkpoint_period": post_all,
        "pre_post_relative_pct": pre_post_pct,
        "treatment": post_treatment,
        "control": post_control,
        "treatment_vs_control_relative_pct": arm_pct,
        "pre_launch_arm_imbalance_pct": pre_arm_pct,
        "difference_in_differences_pct": did_pct,
        "minimum_detectable_effect_pct": mde,
        "exceeds_mde": exceeds_mde,
        "warnings": warnings,
    }


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    parser.add_argument("--metric", help="Restrict to a single metric.")
    args = parser.parse_args()

    brief = _cli.load_brief(args.brief)
    conn = _store.open_store(args.data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], args.checkpoint, conn)

    if args.metric:
        targets = [{"metric": args.metric, "role": "requested"}]
    else:
        targets = contract_metrics(brief)

    results = [movement_for(conn, brief, window, t["metric"], t["role"]) for t in targets]

    payload = _cli.envelope(
        "metric_movement",
        brief,
        window,
        metrics=results,
        interpretation_rules=[
            "treatment_vs_control_relative_pct is the only movement attributable to the feature.",
            "A pre/post movement of similar size in both arms is not a feature effect.",
            "When exceeds_mde is false, the supportable statement is 'no detectable change'.",
        ],
    )
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
