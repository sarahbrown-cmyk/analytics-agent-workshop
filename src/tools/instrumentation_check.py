#!/usr/bin/env python3
"""Event completeness, schema drift, and which metrics are affected.

Checks every event the launch contract calls critical against the contract's
completeness floor, and — the part that makes this useful rather than decorative
— maps each failing event back to the metrics derived from it, using
`metric_definitions.depends_on_events`.

That mapping is what lets the agent say something precise:

    "subscription_conversion_rate is derived from payment_completed, whose
     completeness on Android/GB is 58% against a 95% floor, therefore the
     measured conversion decline in that cell is not reliable evidence about
     purchasing behaviour."

instead of something vague and unfalsifiable like "there may be data issues".

Absent coverage is reported as `no_coverage`, never as healthy. An event with no
instrumentation rows has not passed a check; it has not been checked.

Usage:
    python3 src/tools/instrumentation_check.py --checkpoint 30
    python3 src/tools/instrumentation_check.py --event payment_completed
"""

from __future__ import annotations

import sys

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli, _store, _windows, metric_definitions
else:
    from . import _cli, _store, _windows, metric_definitions

NULL_RATE_CEILING = 0.05


def metrics_depending_on(event: str) -> list[str]:
    return [
        metric
        for metric, definition in metric_definitions.DEFINITIONS.items()
        if event in definition.get("depends_on_events", [])
    ]


def check(conn, brief, window, only_event: str | None) -> dict:
    requirements = brief.get("instrumentation_requirements", {})
    floor = float(requirements.get("completeness_floor_pct", 95.0)) / 100.0
    critical = [entry["event"] for entry in requirements.get("critical_events", [])]
    if only_event:
        critical = [only_event]

    expected_platforms = brief["launch"].get("target_platforms", [])
    expected_markets = brief["launch"].get("eligible_markets", [])

    rows = _store.query(
        conn,
        """
        SELECT event_name, platform, market,
               SUM(observed_volume) AS observed,
               SUM(expected_volume) AS expected,
               MIN(completeness_pct) AS worst_completeness,
               AVG(completeness_pct) AS mean_completeness,
               MAX(schema_version) AS max_schema_version,
               MIN(schema_version) AS min_schema_version,
               MAX(schema_changed) AS schema_changed,
               MAX(null_rate_key_property) AS worst_null_rate
        FROM instrumentation_health
        WHERE date BETWEEN ? AND ?
        GROUP BY event_name, platform, market
        """,
        [window.post_start, window.post_end],
    )
    observed_keys = {(r["event_name"], r["platform"], r["market"]) for r in rows}

    findings = []
    for row in rows:
        if row["event_name"] not in critical:
            continue
        mean_completeness = row["mean_completeness"] or 0.0
        below_floor = mean_completeness < floor
        schema_drift = row["max_schema_version"] != row["min_schema_version"]
        null_spike = (row["worst_null_rate"] or 0.0) > NULL_RATE_CEILING

        if below_floor:
            status = "below_floor"
        elif schema_drift or null_spike:
            status = "warning"
        else:
            status = "healthy"

        affected = metrics_depending_on(row["event_name"])
        findings.append(
            {
                "event": row["event_name"],
                "platform": row["platform"],
                "market": row["market"],
                "evidence_id": _cli.evidence_id(
                    "INS", row["event_name"], row["platform"], row["market"], f"d{window.checkpoint_days}"
                ),
                "mean_completeness_pct": round(mean_completeness * 100, 2),
                "worst_daily_completeness_pct": round((row["worst_completeness"] or 0.0) * 100, 2),
                "completeness_floor_pct": round(floor * 100, 2),
                "schema_version_range": [row["min_schema_version"], row["max_schema_version"]],
                "schema_changed_in_window": bool(row["schema_changed"]),
                "worst_null_rate_key_property": round(row["worst_null_rate"] or 0.0, 4),
                "status": status,
                "metrics_affected": affected,
                "note": _note(status, row, floor, affected),
            }
        )

    coverage_gaps = []
    for event in critical:
        for platform in expected_platforms:
            for market in expected_markets:
                if (event, platform, market) not in observed_keys:
                    coverage_gaps.append(
                        {
                            "event": event,
                            "platform": platform,
                            "market": market,
                            "status": "no_coverage",
                            "metrics_affected": metrics_depending_on(event),
                            "note": (
                                f"No instrumentation rows for {event} on "
                                f"{platform}/{market} in the checkpoint window. This "
                                f"event has not been verified, which is different "
                                f"from having passed. Metrics derived from it cannot "
                                f"be reported as trustworthy in this cell."
                            ),
                        }
                    )

    failing = [f for f in findings if f["status"] == "below_floor"]
    untrustworthy_metrics = sorted(
        {m for f in failing for m in f["metrics_affected"]}
        | {m for g in coverage_gaps for m in g["metrics_affected"]}
    )

    return {
        "completeness_floor_pct": round(floor * 100, 2),
        "critical_events": critical,
        "evidence_id": _cli.evidence_id("INS", "summary", f"d{window.checkpoint_days}"),
        "checks": findings,
        "below_floor": failing,
        "coverage_gaps": coverage_gaps,
        "metrics_not_trustworthy": untrustworthy_metrics,
        "instrumentation_healthy": not failing and not coverage_gaps,
    }


def _note(status: str, row: dict, floor: float, affected: list[str]) -> str:
    if status == "healthy":
        return "Completeness within floor, no schema drift, null rate normal."
    parts = []
    if (row["mean_completeness"] or 0.0) < floor:
        parts.append(
            f"Completeness {row['mean_completeness'] * 100:.1f}% is below the "
            f"{floor * 100:.0f}% floor."
        )
    if row["max_schema_version"] != row["min_schema_version"]:
        parts.append(
            f"Schema version changed from {row['min_schema_version']} to "
            f"{row['max_schema_version']} inside the window."
        )
    if (row["worst_null_rate"] or 0.0) > NULL_RATE_CEILING:
        parts.append(
            f"Null rate on a required property reached "
            f"{row['worst_null_rate'] * 100:.1f}%."
        )
    if affected:
        parts.append(
            "Metrics derived from this event and therefore not reliable here: "
            + ", ".join(affected)
            + "."
        )
    return " ".join(parts)


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    parser.add_argument("--event", help="Restrict to a single event.")
    args = parser.parse_args()

    brief = _cli.load_brief(args.brief)
    conn = _store.open_store(args.data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], args.checkpoint, conn)

    if _store.table_is_empty(conn, "instrumentation_health"):
        payload = _cli.envelope(
            "instrumentation_check",
            brief,
            window,
            instrumentation=None,
            error="instrumentation_health.csv is absent or empty for this data directory.",
        )
        payload["data_quality_warnings"] = list(window.notes) + [
            "No instrumentation data at all. Measurement integrity is unverified, "
            "so no metric in this run can be described as confirmed user behaviour."
        ]
        _cli.emit(payload, args.compact)
        return

    payload = _cli.envelope(
        "instrumentation_check",
        brief,
        window,
        instrumentation=check(conn, brief, window, args.event),
        interpretation_rules=[
            "An event below the completeness floor makes every metric derived from it unreliable in that cell.",
            "no_coverage means unverified, not healthy.",
            "A schema change inside the window is a competing explanation for any movement in the same window.",
        ],
    )
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
