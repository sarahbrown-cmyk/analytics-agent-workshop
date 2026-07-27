#!/usr/bin/env python3
"""Which funnel step changed, and whether the change is physically possible.

Step-to-step pass-through, before and after the checkpoint, plus one check that
is worth the whole tool:

`impossible_ordering` — a step whose observed volume fell while the step *after*
it held steady. Users cannot activate subscriptions they never paid for. When the
later step is unaffected, the earlier step is not being performed less often, it
is being *recorded* less often. That single comparison separates "our users
stopped converting" from "our event stopped firing", and the two lead to
completely different decisions.

Usage:
    python3 src/tools/funnel_analysis.py --checkpoint 30
    python3 src/tools/funnel_analysis.py --platform Android --market GB
"""

from __future__ import annotations

import sys

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli, _store, _windows
else:
    from . import _cli, _store, _windows

# A step must drop by more than this to be worth reporting.
MATERIAL_DROP_PCT = 8.0

# The downstream step is "holding" if it moved less than this.
DOWNSTREAM_HOLDING_PCT = 4.0


def step_volumes(conn, start: str, end: str, filters: dict) -> dict[str, dict]:
    where = ["date BETWEEN ? AND ?"]
    params: list = [start, end]
    for column, value in filters.items():
        where.append(f"{column} = ?")
        params.append(value)
    rows = _store.query(
        conn,
        f"""
        SELECT funnel_step, MIN(step_index) AS step_index,
               SUM(observed_count) AS total,
               COUNT(DISTINCT date) AS days
        FROM funnel_events
        WHERE {' AND '.join(where)}
        GROUP BY funnel_step
        ORDER BY step_index
        """,
        params,
    )
    return {
        row["funnel_step"]: {
            "step_index": int(row["step_index"]),
            "total": row["total"],
            "per_day": round(row["total"] / row["days"], 1) if row["days"] else None,
        }
        for row in rows
    }


def analyse(conn, brief, window, filters: dict) -> dict:
    steps = brief.get("required_funnel", {}).get("steps", [])
    pre = step_volumes(conn, window.pre_start, window.pre_end, filters)
    post = step_volumes(conn, window.post_start, window.post_end, filters)

    # Within the checkpoint window, split halves — a step change partway through
    # is invisible in a window total.
    from datetime import date, timedelta

    post_start = date.fromisoformat(window.post_start)
    post_end = date.fromisoformat(window.post_end)
    mid = post_start + timedelta(days=((post_end - post_start).days + 1) // 2)
    first_half = step_volumes(conn, post_start.isoformat(), (mid - timedelta(days=1)).isoformat(), filters)
    second_half = step_volumes(conn, mid.isoformat(), post_end.isoformat(), filters)

    results = []
    previous_per_day = None
    for step in steps:
        post_entry = post.get(step, {})
        per_day = post_entry.get("per_day")
        pass_through = None
        if previous_per_day and per_day is not None:
            pass_through = round(per_day / previous_per_day, 4)

        half_change = _store.relative_change_pct(
            first_half.get(step, {}).get("per_day"),
            second_half.get(step, {}).get("per_day"),
        )

        results.append(
            {
                "funnel_step": step,
                "evidence_id": _cli.evidence_id(
                    "FUN", step, *(f"{k}-{v}" for k, v in filters.items()), f"d{window.checkpoint_days}"
                ),
                "pre_period_per_day": pre.get(step, {}).get("per_day"),
                "checkpoint_per_day": per_day,
                "pass_through_from_previous_step": pass_through,
                "first_half_per_day": first_half.get(step, {}).get("per_day"),
                "second_half_per_day": second_half.get(step, {}).get("per_day"),
                "second_vs_first_half_pct": half_change,
            }
        )
        if per_day:
            previous_per_day = per_day

    contradictions = _impossible_ordering(results)

    return {
        "filters": filters,
        "evidence_id": _cli.evidence_id(
            "FUN", "funnel", *(f"{k}-{v}" for k, v in filters.items()), f"d{window.checkpoint_days}"
        ),
        "steps": results,
        "material_step_drops": [
            {
                "funnel_step": r["funnel_step"],
                "second_vs_first_half_pct": r["second_vs_first_half_pct"],
                "evidence_id": r["evidence_id"],
            }
            for r in results
            if r["second_vs_first_half_pct"] is not None
            and r["second_vs_first_half_pct"] <= -MATERIAL_DROP_PCT
        ],
        "impossible_ordering": contradictions,
    }


def _impossible_ordering(results: list[dict]) -> list[dict]:
    """A step fell while the step after it held. Recording problem, not behaviour."""
    findings = []
    for index, current in enumerate(results[:-1]):
        following = results[index + 1]
        current_change = current["second_vs_first_half_pct"]
        following_change = following["second_vs_first_half_pct"]
        if current_change is None or following_change is None:
            continue
        if current_change > -MATERIAL_DROP_PCT:
            continue
        if abs(following_change) > DOWNSTREAM_HOLDING_PCT:
            continue

        current_volume = current["second_half_per_day"] or 0
        following_volume = following["second_half_per_day"] or 0
        findings.append(
            {
                "step": current["funnel_step"],
                "step_change_pct": current_change,
                "downstream_step": following["funnel_step"],
                "downstream_change_pct": following_change,
                "downstream_exceeds_step": following_volume > current_volume,
                "verdict": "measurement_suspected",
                "note": (
                    f"{current['funnel_step']} fell {abs(current_change):.1f}% while "
                    f"{following['funnel_step']} held at {following_change:+.1f}%. "
                    f"A genuine drop in {current['funnel_step']} would reduce every "
                    f"step after it. This pattern is consistent with the "
                    f"{current['funnel_step']} event under-reporting, not with users "
                    f"behaving differently."
                    + (
                        f" Observed {following['funnel_step']} volume now EXCEEDS "
                        f"{current['funnel_step']} volume, which is not physically "
                        f"possible and confirms under-reporting."
                        if following_volume > current_volume
                        else ""
                    )
                ),
                "evidence_id": current["evidence_id"],
            }
        )
    return findings


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    parser.add_argument("--platform")
    parser.add_argument("--market")
    args = parser.parse_args()

    brief = _cli.load_brief(args.brief)
    conn = _store.open_store(args.data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], args.checkpoint, conn)

    if _store.table_is_empty(conn, "funnel_events"):
        _cli.emit(
            _cli.envelope(
                "funnel_analysis",
                brief,
                window,
                error="funnel_events.csv is absent or empty for this data directory.",
                funnel=None,
                data_quality_warnings=window.notes
                + ["No funnel data available. Funnel-stage claims cannot be supported."],
            ),
            args.compact,
        )
        return

    filters = {k: v for k, v in (("platform", args.platform), ("market", args.market)) if v}
    payload = _cli.envelope(
        "funnel_analysis",
        brief,
        window,
        funnel=analyse(conn, brief, window, filters),
        interpretation_rules=[
            "A step drop with a holding downstream step is a measurement finding, not a behaviour finding.",
            "Do not describe a drop in an event count as users doing less until the downstream step confirms it.",
            "Pass-through changes are only comparable when the same filters are applied to both periods.",
        ],
    )
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
