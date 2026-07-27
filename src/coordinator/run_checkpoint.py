#!/usr/bin/env python3
"""Gather every deterministic result for a checkpoint into one evidence bundle.

The coordinator agent and the specialists can call the tools in `src/tools/`
individually — that is what they do during the workshop, and it is how a real
investigation proceeds. This script exists for the other two situations:

1. The evaluation harness needs the full set of verified numbers for a scenario
   without invoking a model at all.
2. `report_contract.py` needs the authoritative list of evidence ids that were
   genuinely produced, so it can reject a report citing anything else.

Nothing here interprets. It calls tools and collects their output.

    python3 src/coordinator/run_checkpoint.py --checkpoint 30
    python3 src/coordinator/run_checkpoint.py --data-dir evaluations/cases/03-instrumentation-failure/data
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from tools import (  # noqa: E402
    _cli,
    _store,
    _windows,
    funnel_analysis,
    guardrail_check,
    instrumentation_check,
    launch_context,
    metric_movement,
    segment_breakdown,
)


def collect_evidence_ids(node, found: set[str]) -> set[str]:
    """Every evidence id anywhere in the collected tool output."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence_id" and isinstance(value, str):
                found.add(value)
            else:
                collect_evidence_ids(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_evidence_ids(item, found)
    return found


def build(brief_path: str, checkpoint: int, data_dir: str | None) -> dict:
    brief = _cli.load_brief(brief_path)
    conn = _store.open_store(data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], checkpoint, conn)

    metrics = [
        metric_movement.movement_for(conn, brief, window, entry["metric"], entry["role"])
        for entry in metric_movement.contract_metrics(brief)
    ]

    # Segment every metric the contract cares about across the required groupings.
    groupings = segment_breakdown.required_segment_sets(brief)
    segments = {}
    for entry in metric_movement.contract_metrics(brief):
        metric = entry["metric"]
        segments[metric] = [
            segment_breakdown.breakdown(conn, brief, window, metric, dims, {})
            for dims in groupings
        ]

    guardrails = guardrail_check.evaluate(conn, brief, window)
    instrumentation = (
        None
        if _store.table_is_empty(conn, "instrumentation_health")
        else instrumentation_check.check(conn, brief, window, None)
    )

    # Funnels: overall, and for each platform-market cell that showed a step
    # change in any metric — those are the cells worth the extra queries.
    focus_cells = set()
    for breakdowns in segments.values():
        for breakdown in breakdowns:
            if breakdown["grouped_by"] != ["platform", "market"]:
                continue
            for step in breakdown["step_changes_within_window"]:
                focus_cells.add((step["segment"]["platform"], step["segment"]["market"]))
            # A sustained decline never registers as a step change, so pick up
            # materially declining cells too — otherwise a real, gradual segment
            # regression gets no funnel or context lookup at all.
            for decline in breakdown["largest_declines"]:
                if (decline.get("relative_change_pct") or 0) <= -5.0:
                    focus_cells.add((decline["segment"]["platform"], decline["segment"]["market"]))
    for entry in guardrails["guardrails"]:
        for breach in entry["segment_breaches"]:
            segment = breach["segment"]
            if "platform" in segment and "market" in segment:
                focus_cells.add((segment["platform"], segment["market"]))

    funnels = []
    if not _store.table_is_empty(conn, "funnel_events"):
        funnels.append(funnel_analysis.analyse(conn, brief, window, {}))
        for platform, market in sorted(focus_cells):
            funnels.append(
                funnel_analysis.analyse(conn, brief, window, {"platform": platform, "market": market})
            )

    contexts = [launch_context.gather(brief, window, data_dir, None, None)]
    for platform, market in sorted(focus_cells):
        contexts.append(launch_context.gather(brief, window, data_dir, platform, market))

    bundle = {
        "feature_id": brief["feature"]["id"],
        "brief_version": brief["feature"].get("version"),
        "checkpoint_days": checkpoint,
        "data_dir": data_dir or "synthetic_data",
        "window": window.as_dict(),
        "data_quality_warnings": list(window.notes),
        "focus_cells": [{"platform": p, "market": m} for p, m in sorted(focus_cells)],
        "metric_movement": metrics,
        "segment_breakdowns": segments,
        "guardrail_status": guardrails,
        "instrumentation": instrumentation,
        "funnels": funnels,
        "launch_context": contexts,
    }
    if instrumentation is None:
        bundle["data_quality_warnings"].append(
            "No instrumentation data available. Measurement integrity is unverified."
        )
    bundle["evidence_ids"] = sorted(collect_evidence_ids(bundle, set()))
    return bundle


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    parser.add_argument("--out", help="Write the bundle here instead of stdout.")
    args = parser.parse_args()

    bundle = build(args.brief, args.checkpoint, args.data_dir)

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle, indent=2, default=str) + "\n", encoding="utf-8")
        try:
            shown = out.relative_to(REPO_ROOT)
        except ValueError:
            shown = out  # written outside the repository, show the full path
        print(f"evidence bundle: {shown} ({len(bundle['evidence_ids'])} evidence ids)")
    else:
        _cli.emit(bundle, args.compact)


if __name__ == "__main__":
    main()
