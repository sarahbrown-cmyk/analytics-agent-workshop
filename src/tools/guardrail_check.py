#!/usr/bin/env python3
"""Guardrail evaluation against the thresholds in the launch contract.

Deliberately boring, and deliberately not a judgment call. Each guardrail in the
contract carries a direction, a relative breach threshold, and sometimes an
absolute floor. This tool applies them and returns `pass`, `warn` or `breach`.

Two design choices matter:

**Guardrails are checked at segment level, not just in aggregate.** The primary
scenario in this repository has a guardrail that is comfortably fine in aggregate
and badly breached in one cell. Aggregate-only guardrails would have passed it.

**The threshold lives in the contract, not in this file.** Change what counts as a
breach by editing `feature_briefs/*.yaml`, which is reviewable by anyone on the
team, rather than by editing Python.

Usage:
    python3 src/tools/guardrail_check.py --checkpoint 30
"""

from __future__ import annotations

import math
import sys

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli, _store, _windows
else:
    from . import _cli, _store, _windows

# A breach at 60% of the threshold is a warning: close enough that the next
# checkpoint should expect it.
WARN_FRACTION = 0.6

# Cells smaller than this are reported but never escalated on their own.
MIN_DENOMINATOR_FOR_BREACH = 2000

# A threshold with no noise check manufactures alarms. Split a guardrail across
# eight platform-market cells and some cell will cross 5% by chance alone; page
# someone every time and the guardrail stops meaning anything. A breach must
# clear both the contract threshold and roughly 95% sampling noise for the cell.
NOISE_Z = 1.96

# Real product metrics are overdispersed relative to binomial: day-to-day
# variance exceeds what sampling alone predicts, because users are not
# independent coin flips. Widening the band by this factor keeps small-cell
# noise from being reported as a breach. Tightening it produces more alarms,
# most of them false — which is a tuning decision the team owns, so it lives
# here as a named constant rather than inline in the comparison.
OVERDISPERSION = 1.5


def evaluate(conn, brief, window) -> dict:
    guardrails = brief.get("guardrail_metrics", [])
    results = []

    for guardrail in guardrails:
        metric = guardrail["metric"]
        direction = guardrail.get("direction", "must_not_decrease")
        threshold = float(guardrail.get("breach_relative_pct", 5.0))
        floor = guardrail.get("breach_absolute_floor")
        severity = guardrail.get("severity", "critical")

        aggregate = _assess(
            conn, metric, window, {}, direction, threshold, floor, "aggregate"
        )
        segments = [
            _assess(
                conn,
                metric,
                window,
                {"platform": row["platform"], "market": row["market"]},
                direction,
                threshold,
                floor,
                "platform x market",
            )
            for row in _store.query(
                conn,
                "SELECT DISTINCT platform, market FROM daily_metrics "
                "WHERE metric_name = ? ORDER BY platform, market",
                [metric],
            )
        ]

        breaching = [s for s in segments if s["status"] == "breach"]
        warned = [s for s in segments if s["status"] == "warn"]
        worst = min(
            (s for s in segments if s["relative_change_pct"] is not None),
            key=lambda s: s["relative_change_pct"],
            default=None,
        )

        status = "breach" if aggregate["status"] == "breach" or breaching else (
            "warn" if aggregate["status"] == "warn" or any(s["status"] == "warn" for s in segments)
            else "pass"
        )

        results.append(
            {
                "metric": metric,
                "severity": severity,
                "direction": direction,
                "breach_relative_pct": threshold,
                "breach_absolute_floor": floor,
                "evidence_id": _cli.evidence_id("GRD", metric, f"d{window.checkpoint_days}"),
                "aggregate": aggregate,
                "segment_breaches": breaching,
                "worst_segment": worst,
                "status": status,
                "note": _summary_note(metric, aggregate, breaching, warned),
            }
        )

    breached = [r for r in results if r["status"] == "breach"]
    return {
        "guardrails": results,
        "breached": [r["metric"] for r in breached],
        "warned": [r["metric"] for r in results if r["status"] == "warn"],
        "all_pass": not breached and not any(r["status"] == "warn" for r in results),
        "escalation_required": bool(breached),
        "escalation_reason": (
            "; ".join(
                f"{r['metric']} breached in "
                + ", ".join(
                    "/".join(str(v) for v in s["segment"].values()) for s in r["segment_breaches"]
                )
                if r["segment_breaches"]
                else f"{r['metric']} breached in aggregate"
                for r in breached
            )
            or None
        ),
    }


def _relative_change_noise_pct(pre_row: dict, post_row: dict) -> float | None:
    """Approximate 1-sigma sampling noise on the relative change, in percent.

    Binomial standard errors on each period, combined with the delta method. Valid
    for the rate guardrails in this repository; a mean-valued guardrail would need
    its own variance and is not attempted here rather than being faked.
    """
    p1, p2 = pre_row.get("value"), post_row.get("value")
    n1, n2 = pre_row.get("denominator"), post_row.get("denominator")
    if not all(isinstance(v, (int, float)) for v in (p1, p2, n1, n2)):
        return None
    if not p1 or not p2 or not n1 or not n2 or p1 >= 1 or p2 >= 1:
        return None
    se1 = math.sqrt(p1 * (1 - p1) / n1)
    se2 = math.sqrt(p2 * (1 - p2) / n2)
    ratio = p2 / p1
    return ratio * math.sqrt((se2 / p2) ** 2 + (se1 / p1) ** 2) * 100.0


def _assess(conn, metric, window, filters, direction, threshold, floor, level) -> dict:
    pre = _store.rate(conn, metric, window.pre_start, window.pre_end, filters)
    post = _store.rate(conn, metric, window.post_start, window.post_end, filters)
    pre_row = pre[0] if pre else {}
    post_row = post[0] if post else {}
    pre_value = pre_row.get("value")
    post_value = post_row.get("value")
    denominator = post_row.get("denominator") or 0
    change = _store.relative_change_pct(pre_value, post_value)

    status = "pass"
    reasons: list[str] = []

    if post_value is None or not denominator:
        return {
            "level": level,
            "segment": filters,
            "pre_value": _store.round_or_none(pre_value),
            "checkpoint_value": None,
            "relative_change_pct": None,
            "checkpoint_denominator": denominator,
            "status": "no_data",
            "reasons": ["No data for this guardrail in this cell. Unverified, not passing."],
        }

    noise_pct = _relative_change_noise_pct(pre_row, post_row)
    noise_band = (
        None if noise_pct is None else round(NOISE_Z * OVERDISPERSION * noise_pct, 3)
    )

    adverse = -change if direction == "must_not_decrease" else change
    distinguishable = noise_band is None or adverse >= noise_band

    if adverse >= threshold and distinguishable:
        status = "breach"
        reasons.append(
            f"Moved {change:+.2f}% against a {direction} guardrail with a "
            f"{threshold}% breach threshold."
        )
        if noise_band is not None:
            reasons.append(
                f"Outside sampling noise for this cell (±{noise_band:.2f}%)."
            )
    elif adverse >= threshold and not distinguishable:
        status = "warn"
        reasons.append(
            f"Moved {change:+.2f}%, past the {threshold}% threshold but inside "
            f"sampling noise for this cell (±{noise_band:.2f}%). Not escalated on "
            f"its own: report the movement, do not call it a breach."
        )
    elif adverse >= threshold * WARN_FRACTION:
        status = "warn"
        reasons.append(
            f"Moved {change:+.2f}%, within {WARN_FRACTION:.0%} of the "
            f"{threshold}% breach threshold."
        )

    if floor is not None and post_value < float(floor):
        status = "breach"
        reasons.append(
            f"Absolute value {post_value:.4f} is below the contract floor of {floor}."
        )

    if status == "breach" and denominator < MIN_DENOMINATOR_FOR_BREACH:
        status = "warn"
        reasons.append(
            f"Downgraded to warn: only {denominator:.0f} in the denominator, too "
            f"small to escalate on its own."
        )

    return {
        "level": level,
        "segment": filters,
        "pre_value": _store.round_or_none(pre_value),
        "checkpoint_value": _store.round_or_none(post_value),
        "relative_change_pct": change,
        "checkpoint_denominator": denominator,
        "sampling_noise_band_pct": noise_band,
        "status": status,
        "reasons": reasons,
    }


def _summary_note(metric, aggregate, breaching, warned=()) -> str:
    cells = ", ".join("/".join(str(v) for v in b["segment"].values()) for b in breaching)
    warned_cells = ", ".join("/".join(str(v) for v in w["segment"].values()) for w in warned)
    if aggregate["status"] == "breach":
        if breaching:
            return f"{metric} breaches in aggregate and in {cells}."
        return f"{metric} breaches in aggregate."
    if breaching:
        return (
            f"{metric} does not breach in aggregate ({aggregate['relative_change_pct']:+.2f}%, "
            f"status {aggregate['status']}) but breaches in {cells}. An aggregate-only "
            f"guardrail check would have missed this."
        )
    if aggregate["status"] == "warn":
        return f"{metric} approaching its threshold in aggregate; no segment breach."
    if warned_cells:
        return (
            f"{metric} within thresholds in aggregate, with movement worth watching "
            f"in {warned_cells}. No breach."
        )
    return f"{metric} within contract thresholds at aggregate and segment level."


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    args = parser.parse_args()

    brief = _cli.load_brief(args.brief)
    conn = _store.open_store(args.data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], args.checkpoint, conn)

    payload = _cli.envelope(
        "guardrail_check",
        brief,
        window,
        guardrail_status=evaluate(conn, brief, window),
        interpretation_rules=[
            "A guardrail breach requires escalation regardless of how good the primary outcome looks.",
            "status=no_data means unverified. Do not report it as passing.",
            "A breach is a fact about the metric. It is not by itself a fact about the cause.",
        ],
    )
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
