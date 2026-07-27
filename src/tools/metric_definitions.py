#!/usr/bin/env python3
"""Governed metric definitions.

FICTIONAL definitions invented for the workshop.

This registry is the reason the specialists can be told "use governed
definitions" and have it mean something. A metric here is not a name — it is a
numerator, a denominator, an owner, a version, and, critically, the **events it
is derived from**.

That last field is what lets the instrumentation analyst do its job. When
`payment_completion_rate` moves, the agent can establish that the metric is
computed from the `payment_completed` event, and therefore that a drop in that
event's completeness is a competing explanation for the movement — not a separate,
unrelated observation. Without the dependency recorded here, connecting the two
would be guesswork.

Usage:
    python3 src/tools/metric_definitions.py
    python3 src/tools/metric_definitions.py --metric payment_completion_rate
"""

from __future__ import annotations

import argparse
import json
import sys

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli
else:
    from . import _cli


DEFINITIONS: dict[str, dict] = {
    "feature_adoption_rate": {
        "display_name": "Feature adoption rate",
        "numerator": "Eligible users who sent at least one priority introduction in the period",
        "denominator": "Eligible users in the period",
        "grain": "user",
        "owner": "lifecycle-analytics",
        "version": "3.1.0",
        "depends_on_events": ["priority_intro_sent"],
        "notes": "Undefined for the control arm — control users cannot adopt a feature they cannot see.",
    },
    "mutual_connection_rate": {
        "display_name": "Mutual connection rate",
        "numerator": "Users with at least one new mutual connection in the period",
        "denominator": "Active users in the period",
        "grain": "user",
        "owner": "core-analytics",
        "version": "5.4.2",
        "depends_on_events": ["connection_created"],
        "notes": "Server-side derived. Not dependent on client instrumentation.",
    },
    "subscription_conversion_rate": {
        "display_name": "Subscription conversion rate",
        "numerator": "Free users who completed a subscription payment in the period",
        "denominator": "Free users in the period",
        "grain": "user",
        "owner": "monetization-analytics",
        "version": "4.0.1",
        "depends_on_events": ["payment_completed"],
        "notes": (
            "Derived from the client payment_completed event. If that event "
            "under-reports, this metric under-reports with it, and the movement "
            "is a measurement artifact rather than a change in purchasing."
        ),
    },
    "session_frequency": {
        "display_name": "Session frequency",
        "numerator": "Sessions started in the period",
        "denominator": "Active users in the period",
        "grain": "user",
        "owner": "core-analytics",
        "version": "2.7.0",
        "depends_on_events": ["session_start"],
        "notes": "A mean, not a rate. Do not read values above 1.0 as a percentage.",
    },
    "report_block_rate": {
        "display_name": "Report or block rate",
        "numerator": "Users who reported or blocked another user in the period",
        "denominator": "Active users in the period",
        "grain": "user",
        "owner": "trust-safety-analytics",
        "version": "6.2.0",
        "depends_on_events": ["user_reported", "user_blocked"],
        "notes": "Guardrail. An increase is a harm signal, not a neutral movement.",
    },
    "day7_retention_proxy": {
        "display_name": "Day-7 retention proxy",
        "numerator": "Users active on any of days 5-9 after their period-anchor session",
        "denominator": "Users with a period-anchor session",
        "grain": "user",
        "owner": "lifecycle-analytics",
        "version": "1.9.3",
        "depends_on_events": ["session_start"],
        "notes": (
            "A proxy, not retention. Deliberately named so nobody reports it as "
            "day-7 retention in a leadership summary."
        ),
    },
    "payment_completion_rate": {
        "display_name": "Payment completion rate",
        "numerator": "Checkouts with a completed payment in the period",
        "denominator": "Checkouts started in the period",
        "grain": "checkout",
        "owner": "monetization-analytics",
        "version": "4.0.1",
        "depends_on_events": ["checkout_started", "payment_completed"],
        "notes": (
            "Guardrail. Compare against subscription_activated, which is recorded "
            "server-side: if activations hold while completions fall, the payment "
            "event is under-reporting."
        ),
    },
}


def get(metric: str) -> dict | None:
    return DEFINITIONS.get(metric)


def require(metric: str) -> dict:
    definition = DEFINITIONS.get(metric)
    if definition is None:
        raise KeyError(
            f"{metric!r} has no governed definition. Add one to "
            f"src/tools/metric_definitions.py before reporting on it."
        )
    return definition


def events_for(metric: str) -> list[str]:
    definition = DEFINITIONS.get(metric)
    return list(definition["depends_on_events"]) if definition else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric", help="Return a single definition.")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    if args.metric:
        definition = DEFINITIONS.get(args.metric)
        if definition is None:
            _cli.fail(
                f"{args.metric!r} has no governed definition. Reporting on an "
                f"undefined metric is not permitted."
            )
        payload = {
            "tool": "metric_definitions",
            "metric": args.metric,
            "evidence_id": _cli.evidence_id("DEF", args.metric),
            "definition": definition,
        }
    else:
        payload = {
            "tool": "metric_definitions",
            "evidence_id": _cli.evidence_id("DEF", "all"),
            "metric_count": len(DEFINITIONS),
            "definitions": DEFINITIONS,
        }
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
