#!/usr/bin/env python3
"""Where an aggregate movement is actually concentrated.

An aggregate is an average of things that are not the same. This tool splits a
metric by the segments the launch contract requires, and computes two things the
model must not be asked to work out for itself:

- `share_of_absolute_movement_pct` — how much of the total movement each cell
  accounts for. A cell that is 6% of users and 80% of the movement is the story.
- `arm_symmetry` — whether the same movement appears in the control arm. This is
  the single most useful check in the repository. A feature shipped only to
  treatment cannot move control. When a decline is symmetric across arms, the
  cause is something else: a release, a processor, an instrumentation change, the
  world. Reporting a symmetric movement as a feature effect is the specific error
  this workshop is built to prevent.

Usage:
    python3 src/tools/segment_breakdown.py --metric subscription_conversion_rate
    python3 src/tools/segment_breakdown.py --metric recommendation_engagement_rate --by platform,market
    python3 src/tools/segment_breakdown.py --metric payment_completion_rate --by market --platform Android
"""

from __future__ import annotations

import sys

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli, _store, _windows, metric_definitions
else:
    from . import _cli, _store, _windows, metric_definitions

VALID_DIMENSIONS = ("platform", "market", "user_type", "assignment", "subscription_status")

# When the smaller arm movement is at least this share of the larger, the two
# arms moved together and a treatment-only feature cannot be the cause.
ARM_SYMMETRY_THRESHOLD = 0.5

# Below this relative change, a cell has not moved in any way worth explaining.
MATERIAL_MOVEMENT_PCT = 2.0

# Half-over-half change that indicates a step change rather than a drift.
STEP_CHANGE_PCT = 8.0


def required_segment_sets(brief: dict) -> list[list[str]]:
    """Translate the contract's required_segments into groupings this tool runs."""
    sets: list[list[str]] = []
    for entry in brief.get("required_segments", []):
        dims = [d.strip() for d in str(entry).replace("×", "x").split(" x ")]
        dims = [d for d in dims if d in VALID_DIMENSIONS]
        if dims and dims not in sets:
            sets.append(dims)
    return sets


def breakdown(conn, brief, window, metric: str, dims: list[str], filters: dict) -> dict:
    definition = metric_definitions.get(metric)

    pre = {
        _key(row, dims): row
        for row in _store.rate(conn, metric, window.pre_start, window.pre_end, filters, dims)
    }
    post = {
        _key(row, dims): row
        for row in _store.rate(conn, metric, window.post_start, window.post_end, filters, dims)
    }

    # Per-arm views, used for the symmetry check. Skipped when the caller is
    # already grouping by assignment.
    arm_views = {}
    if "assignment" not in dims:
        for arm in ("treatment", "control"):
            arm_filters = dict(filters, assignment=arm)
            arm_views[arm] = {
                "pre": {
                    _key(r, dims): r
                    for r in _store.rate(conn, metric, window.pre_start, window.pre_end, arm_filters, dims)
                },
                "post": {
                    _key(r, dims): r
                    for r in _store.rate(conn, metric, window.post_start, window.post_end, arm_filters, dims)
                },
            }

    cells = []
    total_abs_movement = 0.0
    for key in sorted(set(pre) | set(post)):
        pre_row = pre.get(key, {})
        post_row = post.get(key, {})
        pre_value = pre_row.get("value")
        post_value = post_row.get("value")
        # Movement in numerator terms: how many events the change is worth.
        # Percentage-point change alone would let a tiny cell dominate.
        abs_movement = 0.0
        if pre_value is not None and post_value is not None and post_row.get("denominator"):
            abs_movement = (post_value - pre_value) * float(post_row["denominator"])
        total_abs_movement += abs(abs_movement)

        cell = {
            "segment": dict(zip(dims, key)),
            "evidence_id": _cli.evidence_id(
                "SEG", metric, "-".join(dims), "-".join(str(k) for k in key), f"d{window.checkpoint_days}"
            ),
            "pre_value": _store.round_or_none(pre_value),
            "checkpoint_value": _store.round_or_none(post_value),
            "relative_change_pct": _store.relative_change_pct(pre_value, post_value),
            "checkpoint_denominator": post_row.get("denominator"),
            "absolute_movement_events": round(abs_movement, 1),
        }

        if arm_views:
            cell["arm_symmetry"] = _arm_symmetry(arm_views, key)
        cell["within_window"] = _within_window_change(conn, metric, window, dims, filters, key)

        cells.append(cell)

    for cell in cells:
        cell["share_of_absolute_movement_pct"] = (
            round(abs(cell["absolute_movement_events"]) / total_abs_movement * 100.0, 2)
            if total_abs_movement
            else None
        )

    declining = [c for c in cells if (c["relative_change_pct"] or 0) < 0]
    declining.sort(key=lambda c: c["relative_change_pct"] or 0)

    missing = _missing_cells(conn, brief, dims, filters)

    return {
        "metric": metric,
        "definition_version": (definition or {}).get("version"),
        "grouped_by": dims,
        "filters": filters,
        "evidence_id": _cli.evidence_id(
            "SEG", metric, "-".join(dims), *(f"{k}-{v}" for k, v in filters.items()),
            f"d{window.checkpoint_days}",
        ),
        "cells": cells,
        "largest_declines": [
            {
                "segment": c["segment"],
                "relative_change_pct": c["relative_change_pct"],
                "share_of_absolute_movement_pct": c["share_of_absolute_movement_pct"],
                "arm_symmetry": c.get("arm_symmetry", {}).get("verdict"),
                "second_vs_first_half_pct": c["within_window"]["second_vs_first_half_pct"],
                "step_change_suspected": c["within_window"]["step_change_suspected"],
                "evidence_id": c["evidence_id"],
            }
            for c in declining[:3]
        ],
        "step_changes_within_window": [
            {
                "segment": c["segment"],
                "second_vs_first_half_pct": c["within_window"]["second_vs_first_half_pct"],
                "arm_symmetry": c.get("arm_symmetry", {}).get("verdict"),
                "evidence_id": c["evidence_id"],
            }
            for c in cells
            if c["within_window"]["step_change_suspected"]
        ],
        "segments_expected_but_absent": missing,
    }


def _key(row: dict, dims: list[str]) -> tuple:
    return tuple(row[d] for d in dims)


def _arm_symmetry(arm_views: dict, key: tuple) -> dict:
    """Does this movement also appear in the arm that never saw the feature?

    Compared on the larger of the two magnitudes rather than on treatment alone.
    Dividing by a treatment movement that happens to sit near zero produces a
    huge ratio and a confident wrong verdict — the exact failure mode this whole
    repository is about, so it would be embarrassing to ship it here.
    """
    per_arm = {}
    for arm, view in arm_views.items():
        pre_value = view["pre"].get(key, {}).get("value")
        post_value = view["post"].get(key, {}).get("value")
        per_arm[arm] = _store.relative_change_pct(pre_value, post_value)

    treatment = per_arm.get("treatment")
    control = per_arm.get("control")

    if treatment is None or control is None:
        verdict, note = "undetermined", "Insufficient data in one arm to compare."
    else:
        larger = max(abs(treatment), abs(control))
        smaller = min(abs(treatment), abs(control))
        if larger < MATERIAL_MOVEMENT_PCT:
            verdict = "no_material_movement"
            note = (
                f"Neither arm moved by more than {MATERIAL_MOVEMENT_PCT}%. "
                f"Within noise for this cell size."
            )
        elif abs(treatment) < MATERIAL_MOVEMENT_PCT:
            # Only the arm without the feature moved. Whatever this is, the
            # feature is not it.
            verdict = "control_only"
            note = (
                "The control arm moved but the treatment arm did not. This cannot "
                "be a feature effect. Most often noise at this cell size."
            )
        elif (treatment < 0) != (control < 0) and smaller >= MATERIAL_MOVEMENT_PCT:
            verdict = "opposite_in_control"
            note = "The arms moved materially in opposite directions."
        elif (treatment < 0) == (control < 0) and smaller / larger >= ARM_SYMMETRY_THRESHOLD:
            verdict = "symmetric_across_arms"
            note = (
                "The movement is present in the control arm at a comparable "
                "magnitude. A feature shipped only to treatment cannot cause "
                "this. Look for a release, a payment processor, or a measurement "
                "change affecting both arms."
            )
        else:
            verdict = "treatment_only"
            note = (
                "The movement is concentrated in the treatment arm, which is "
                "consistent with a feature effect. Consistent with, not proof of."
            )

    return {
        "treatment_relative_change_pct": treatment,
        "control_relative_change_pct": control,
        "verdict": verdict,
        "note": note,
    }


def _within_window_change(conn, metric, window, dims, filters, key) -> dict:
    """First half of the checkpoint window vs second half.

    A 30-day average hides a step change that started on day 15: a −33% break
    over half the window reads as −17% for the window, and a −33% break over the
    last six days reads as −7%. Monitoring that only ever compares the whole
    window to the whole pre-period will systematically under-report exactly the
    kind of mid-window failure this checkpoint exists to catch.
    """
    from datetime import date, timedelta

    post_start = date.fromisoformat(window.post_start)
    post_end = date.fromisoformat(window.post_end)
    total_days = (post_end - post_start).days + 1
    mid = post_start + timedelta(days=total_days // 2)

    cell_filters = dict(filters)
    for dim, value in zip(dims, key):
        cell_filters[dim] = value

    early = _store.rate(conn, metric, post_start.isoformat(), (mid - timedelta(days=1)).isoformat(), cell_filters)
    late = _store.rate(conn, metric, mid.isoformat(), post_end.isoformat(), cell_filters)
    early_value = early[0]["value"] if early else None
    late_value = late[0]["value"] if late else None
    change = _store.relative_change_pct(early_value, late_value)

    return {
        "first_half": {"start": post_start.isoformat(), "end": (mid - timedelta(days=1)).isoformat(), "value": _store.round_or_none(early_value)},
        "second_half": {"start": mid.isoformat(), "end": post_end.isoformat(), "value": _store.round_or_none(late_value)},
        "second_vs_first_half_pct": change,
        "step_change_suspected": change is not None and abs(change) >= STEP_CHANGE_PCT,
    }


def _missing_cells(conn, brief, dims: list[str], filters: dict) -> list[dict]:
    """Contract-expected segments with no rows at all — missing, not zero."""
    expected = {
        "platform": brief["launch"].get("target_platforms", []),
        "market": brief["launch"].get("eligible_markets", []),
    }
    missing = []
    for dim in dims:
        if dim not in expected:
            continue
        present = {
            row[dim]
            for row in _store.query(conn, f"SELECT DISTINCT {dim} AS {dim} FROM daily_metrics")
        }
        for value in expected[dim]:
            if value not in present:
                missing.append(
                    {
                        "dimension": dim,
                        "value": value,
                        "note": (
                            f"{dim}={value} is required by the launch contract but "
                            f"absent from the metrics store. Treat as missing data, "
                            f"not as zero."
                        ),
                    }
                )
    return missing


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    parser.add_argument("--metric", required=True)
    parser.add_argument(
        "--by",
        help="Comma-separated dimensions. Omit to run every grouping the contract requires.",
    )
    parser.add_argument("--platform")
    parser.add_argument("--market")
    parser.add_argument("--user-type", dest="user_type")
    parser.add_argument("--subscription-status", dest="subscription_status")
    args = parser.parse_args()

    brief = _cli.load_brief(args.brief)
    conn = _store.open_store(args.data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], args.checkpoint, conn)

    filters = {
        k: v
        for k, v in (
            ("platform", args.platform),
            ("market", args.market),
            ("user_type", args.user_type),
            ("subscription_status", args.subscription_status),
        )
        if v
    }

    if args.by:
        groupings = [[d.strip() for d in args.by.split(",") if d.strip()]]
        for dims in groupings:
            bad = [d for d in dims if d not in VALID_DIMENSIONS]
            if bad:
                _cli.fail(f"unknown dimension(s): {', '.join(bad)}. Valid: {', '.join(VALID_DIMENSIONS)}")
    else:
        groupings = required_segment_sets(brief)

    breakdowns = [breakdown(conn, brief, window, args.metric, dims, filters) for dims in groupings]

    payload = _cli.envelope(
        "segment_breakdown",
        brief,
        window,
        metric=args.metric,
        required_segments_from_contract=brief.get("required_segments", []),
        breakdowns=breakdowns,
        interpretation_rules=[
            "A segment that holds a small share of users and a large share of movement is the finding.",
            "arm_symmetry=symmetric_across_arms rules out a treatment-only feature as the cause.",
            "segments_expected_but_absent are missing data. Never report them as zero or as healthy.",
        ],
    )
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
