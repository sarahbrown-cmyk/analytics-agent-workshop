#!/usr/bin/env python3
"""Generate the shipped report artifacts. Facilitator utility.

Participants never run this. It builds two sets of monitoring reports from each
case's real evidence bundle:

    baseline   evaluations/cases/<case>/baseline_report.json
    solution   solutions/completed/reports/<case>.json

Generating rather than hand-writing them matters for one reason: every figure and
every evidence id comes from an actual tool run, so the baselines cannot contain a
number the tools disagree with or cite an evidence id that does not exist. A
hand-written baseline would fail `numerical_correctness` for reasons nobody
intended, and the workshop would spend its evaluation block debugging the fixture.

The *flaws* in the baselines are deliberate and declared here in one place:

    case 03  the report is analytically correct and escalates on instrumentation.
             It fails because no enabled escalation rule covers that trigger.
             Fix: src/schemas/escalation_rules.yaml.
    case 04  the report blames the feature for a movement that appears in the
             control arm too, and never mentions the overlapping experiment.
             Fix: the reviewer rubric and the analyst instructions, then rerun
             the agent.

Usage:
    python3 evaluations/_make_reports.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for extra in (REPO_ROOT / "src", REPO_ROOT / "evaluations"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from coordinator import run_checkpoint  # noqa: E402
from tools import _yaml  # noqa: E402

BRIEF_PATH = REPO_ROOT / "feature_briefs" / "priority-introductions.yaml"
CASES_DIR = REPO_ROOT / "evaluations" / "cases"
SOLUTION_DIR = REPO_ROOT / "solutions" / "completed" / "reports"

TOOL_BY_PREFIX = {
    "EV-MOV": "metric_movement",
    "EV-SEG": "segment_breakdown",
    "EV-GRD": "guardrail_check",
    "EV-INS": "instrumentation_check",
    "EV-FUN": "funnel_analysis",
    "EV-CTX": "launch_context",
    "EV-DEF": "metric_definitions",
}


# ---------------------------------------------------------------------------
# Helpers that read the bundle so reports never invent numbers
# ---------------------------------------------------------------------------


def movement(bundle: dict, metric: str) -> dict:
    for entry in bundle["metric_movement"]:
        if entry["metric"] == metric:
            return entry
    return {}


def platform_market_breakdown(bundle: dict, metric: str) -> dict:
    for breakdown in bundle["segment_breakdowns"].get(metric, []):
        if breakdown["grouped_by"] == ["platform", "market"]:
            return breakdown
    return {}


def cell(bundle: dict, metric: str, platform: str, market: str) -> dict:
    for entry in platform_market_breakdown(bundle, metric).get("cells", []):
        if entry["segment"] == {"platform": platform, "market": market}:
            return entry
    return {}


def guardrail_items(bundle: dict) -> list[dict]:
    items = []
    for entry in bundle["guardrail_status"]["guardrails"]:
        worst = entry.get("worst_segment") or {}
        segment = worst.get("segment") or {}
        label = "/".join(str(v) for v in segment.values()) if segment else None
        items.append(
            {
                "metric": entry["metric"],
                "status": entry["status"],
                "worst_segment": label,
                "evidence_refs": [entry["evidence_id"]],
            }
        )
    return items


def instrumentation_block(bundle: dict) -> dict:
    instrumentation = bundle.get("instrumentation")
    if instrumentation is None:
        return {
            "status": "unverified",
            "events_below_floor": [],
            "metrics_not_trustworthy": [],
            "evidence_refs": [],
        }
    below = instrumentation.get("below_floor") or []
    gaps = instrumentation.get("coverage_gaps") or []
    if below:
        status = "below_floor"
    elif gaps:
        status = "unverified"
    else:
        status = "healthy"
    refs = [instrumentation["evidence_id"]] + [entry["evidence_id"] for entry in below]
    return {
        "status": status,
        "events_below_floor": sorted({f"{e['event']} ({e['platform']}/{e['market']})" for e in below}),
        "metrics_not_trustworthy": instrumentation.get("metrics_not_trustworthy") or [],
        "evidence_refs": refs,
    }


def funnel_contradictions(bundle: dict) -> list[dict]:
    out = []
    for funnel in bundle.get("funnels", []):
        for finding in funnel.get("impossible_ordering", []):
            out.append({**finding, "filters": funnel.get("filters", {})})
    return out


def context_refs(bundle: dict, identifier: str) -> list[str]:
    return [e for e in bundle["evidence_ids"] if identifier.lower() in e.lower()]


def primary_verdict(bundle: dict, brief: dict, override: str | None = None) -> str:
    if override:
        return override
    entry = movement(bundle, brief["primary_outcome"]["metric"])
    low, high = brief["primary_outcome"]["expected_relative_change_pct"]
    value = entry.get("difference_in_differences_pct")
    if entry.get("exceeds_mde") is False:
        return "no_detectable_change"
    if value is None:
        return "not_measurable"
    if value < low:
        return "below_expected_range"
    if value > high:
        return "above_expected_range"
    return "within_expected_range"


def build_evidence_index(report: dict) -> list[dict]:
    cited: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("evidence_refs") and isinstance(value, list):
                    cited.update(v for v in value if isinstance(v, str))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(report)
    return [
        {
            "evidence_id": ref,
            "tool": TOOL_BY_PREFIX.get(ref[:6], "unknown"),
            "summary": "Deterministic tool output cited by this report.",
        }
        for ref in sorted(cited)
    ]


def shell(bundle: dict, brief: dict) -> dict:
    return {
        "feature_id": bundle["feature_id"],
        "checkpoint_days": bundle["checkpoint_days"],
        "brief_version": bundle["brief_version"],
        "generated_by": "monitoring-coordinator",
        "window": {
            "post_start": bundle["window"]["post_start"],
            "post_end": bundle["window"]["post_end"],
            "pre_start": bundle["window"]["pre_start"],
            "pre_end": bundle["window"]["pre_end"],
            "complete": bundle["window"]["complete"],
        },
        "segments_checked": [str(s) for s in brief.get("required_segments", [])],
        "guardrail_status": {
            "overall": "breach"
            if bundle["guardrail_status"]["breached"]
            else ("warn" if bundle["guardrail_status"]["warned"] else "pass"),
            "items": guardrail_items(bundle),
        },
        "instrumentation_health": instrumentation_block(bundle),
    }


def primary_block(bundle: dict, brief: dict, override: str | None = None) -> dict:
    metric = brief["primary_outcome"]["metric"]
    entry = movement(bundle, metric)
    return {
        "metric": metric,
        "checkpoint_value": entry.get("checkpoint_period", {}).get("value"),
        "treatment_vs_control_relative_pct": entry.get("difference_in_differences_pct"),
        "expected_range_pct": brief["primary_outcome"]["expected_relative_change_pct"],
        "verdict": primary_verdict(bundle, brief, override),
        "evidence_refs": [entry.get("evidence_id")] if entry.get("evidence_id") else [],
    }


# ---------------------------------------------------------------------------
# Per-case report content
# ---------------------------------------------------------------------------


def case_01(bundle, brief, flawed: bool) -> dict:
    report = shell(bundle, brief)
    primary = movement(bundle, brief["primary_outcome"]["metric"])
    adoption = movement(bundle, "feature_adoption_rate")
    report["primary_outcome"] = primary_block(bundle, brief)
    report["executive_summary"] = (
        f"Day-30 checkpoint on Priority Introductions is within contract expectations. "
        f"The primary outcome, mutual_connection_rate, is "
        f"{primary['difference_in_differences_pct']}% higher in treatment than control, "
        f"inside the expected 2.0-4.0% band. All three guardrails are within threshold at "
        f"aggregate and segment level, instrumentation completeness is above the 95% floor "
        f"for every critical event, and no required segment is missing. No escalation is "
        f"required and no further investigation is warranted before the day-60 checkpoint."
    )
    report["segment_findings"] = []
    report["facts"] = [
        {
            "statement": (
                f"mutual_connection_rate is {primary['difference_in_differences_pct']}% higher "
                f"in treatment than control over the checkpoint window, against a minimum "
                f"detectable effect of {primary['minimum_detectable_effect_pct']}%."
            ),
            "evidence_refs": [primary["evidence_id"]],
        },
        {
            "statement": (
                f"Feature adoption among eligible treatment users is "
                f"{round((adoption.get('treatment', {}).get('value') or 0) * 100, 1)}% over the "
                f"window."
            ),
            "evidence_refs": [adoption["evidence_id"]],
        },
        {
            "statement": "All critical events are above the 95% completeness floor in every eligible market.",
            "evidence_refs": report["instrumentation_health"]["evidence_refs"][:1],
        },
    ]
    report["hypotheses"] = []
    report["recommended_actions"] = [
        {
            "action": "Proceed to the day-60 checkpoint with no change to the rollout.",
            "owner": "lifecycle-analytics",
            "rationale": "Primary outcome inside the expected band, no guardrail movement, measurement healthy.",
            "blocks_product_decision": False,
            "evidence_refs": [primary["evidence_id"]],
        }
    ]
    report["confidence_and_escalation"] = {
        "overall_confidence": "high",
        "escalate": False,
        "escalation_reasons": [],
        "escalation_route": None,
    }
    return report


def case_02(bundle, brief, flawed: bool) -> dict:
    report = shell(bundle, brief)
    primary = movement(bundle, brief["primary_outcome"]["metric"])
    ios_de = cell(bundle, brief["primary_outcome"]["metric"], "iOS", "DE")
    retention = movement(bundle, "day7_retention_proxy")
    breakdown = platform_market_breakdown(bundle, brief["primary_outcome"]["metric"])

    report["primary_outcome"] = primary_block(bundle, brief)
    report["executive_summary"] = (
        f"Day-30 checkpoint on Priority Introductions shows no detectable aggregate effect: "
        f"mutual_connection_rate is {primary['difference_in_differences_pct']}% treatment vs "
        f"control, below the {primary['minimum_detectable_effect_pct']}% minimum detectable "
        f"effect. That aggregate is misleading. iOS/DE treatment users show a "
        f"{ios_de['relative_change_pct']}% decline in mutual_connection_rate with no "
        f"equivalent movement in the control arm, which is consistent with a genuine "
        f"feature effect in that market and may be offsetting gains elsewhere. "
        f"Instrumentation is healthy across all events, so this is unlikely to be a "
        f"measurement artefact. Escalating for a human decision on whether to hold the "
        f"German iOS rollout."
    )
    report["segment_findings"] = [
        {
            "segment": "iOS/DE",
            "observation": (
                f"mutual_connection_rate in iOS/DE moved {ios_de['relative_change_pct']}% over "
                f"the window, accounting for {ios_de['share_of_absolute_movement_pct']}% of total "
                f"absolute movement. The treatment arm moved "
                f"{ios_de['arm_symmetry']['treatment_relative_change_pct']}% against "
                f"{ios_de['arm_symmetry']['control_relative_change_pct']}% in control."
            ),
            "arm_symmetry": ios_de["arm_symmetry"]["verdict"],
            "evidence_refs": [ios_de["evidence_id"], breakdown["evidence_id"]],
            "confidence": "medium",
            "limitations": (
                "Single market and platform; no qualitative signal on why German users "
                "respond differently. Sub-segment cell sizes below the market level are not examined."
            ),
        }
    ]
    report["facts"] = [
        {
            "statement": (
                f"Aggregate mutual_connection_rate is {primary['difference_in_differences_pct']}% "
                f"treatment vs control, below the "
                f"{primary['minimum_detectable_effect_pct']}% minimum detectable effect."
            ),
            "evidence_refs": [primary["evidence_id"]],
        },
        {
            "statement": (
                f"mutual_connection_rate in iOS/DE fell {abs(ios_de['relative_change_pct'])}% over "
                f"the window, with the movement confined to the treatment arm."
            ),
            "evidence_refs": [ios_de["evidence_id"]],
        },
        {
            "statement": (
                "Every critical event is above the 95% completeness floor in all eligible markets, "
                "so no metric in this checkpoint is compromised by measurement."
            ),
            "evidence_refs": report["instrumentation_health"]["evidence_refs"][:1],
        },
        {
            "statement": (
                f"day7_retention_proxy is {retention.get('difference_in_differences_pct')}% "
                f"treatment vs control in aggregate and within its guardrail threshold."
            ),
            "evidence_refs": [retention["evidence_id"]],
        },
    ]
    report["hypotheses"] = [
        {
            "statement": (
                "Priority Introductions may suppress mutual connections for German iOS users, "
                "possibly through introduction ranking that suits the local liquidity pattern poorly."
            ),
            "supporting_evidence_refs": [ios_de["evidence_id"]],
            "contradicting_evidence_refs": [primary["evidence_id"]],
            "confidence": "medium",
            "how_to_test": (
                "Compare intro acceptance rate by recipient bucket within iOS/DE treatment "
                "against iOS/US treatment; if ranking is the mechanism, acceptance should differ."
            ),
            "ruled_out": False,
        },
        {
            "statement": (
                "The iOS/DE movement could be a market-specific seasonal or competitive effect "
                "unrelated to the feature."
            ),
            "supporting_evidence_refs": [],
            "contradicting_evidence_refs": [ios_de["evidence_id"]],
            "confidence": "low",
            "how_to_test": (
                "An external effect would move the control arm too. Control moved "
                f"{ios_de['arm_symmetry']['control_relative_change_pct']}%, which argues against this."
            ),
            "ruled_out": False,
        },
    ]
    report["recommended_actions"] = [
        {
            "action": "Hold the German iOS rollout at its current share pending a ranking review.",
            "owner": "product-discovery",
            "rationale": (
                "A treatment-only decline of this size in one market is worth pausing on, and the "
                "aggregate does not justify expanding."
            ),
            "blocks_product_decision": True,
            "evidence_refs": [ios_de["evidence_id"]],
        },
        {
            "action": "Run the intro acceptance comparison for iOS/DE against iOS/US within treatment.",
            "owner": "lifecycle-analytics",
            "rationale": "Cheapest test that separates a ranking mechanism from a market effect.",
            "blocks_product_decision": False,
            "evidence_refs": [ios_de["evidence_id"]],
        },
    ]
    report["confidence_and_escalation"] = {
        "overall_confidence": "medium",
        "escalate": True,
        "escalation_reasons": [
            f"Aggregate primary outcome does not clear the "
            f"{primary['minimum_detectable_effect_pct']}% minimum detectable effect.",
            "A treatment-only decline in iOS/DE requires a product decision on the German rollout.",
        ],
        "escalation_route": brief["human_escalation_route"]["channel"],
    }
    return report


def case_03(bundle, brief, flawed: bool) -> dict:
    """Analytically correct in both variants.

    The baseline fails not because the report is wrong but because the system's
    escalation rules do not cover instrumentation. That is the point of the case:
    a correct analysis can still fail a badly configured gate, and the fix is in
    the configuration rather than in the analysis.
    """
    report = shell(bundle, brief)
    primary = movement(bundle, brief["primary_outcome"]["metric"])
    adoption = movement(bundle, "feature_adoption_rate")
    android_us = cell(bundle, "feature_adoption_rate", "Android", "US")
    breakdown = platform_market_breakdown(bundle, "feature_adoption_rate")
    instrumentation = bundle["instrumentation"]
    below = instrumentation["below_floor"][0]
    contradictions = funnel_contradictions(bundle)
    contradiction = next(
        (c for c in contradictions if c["filters"].get("market") == "US"), contradictions[0]
    )
    release_refs = context_refs(bundle, "rel-1058")

    report["primary_outcome"] = primary_block(bundle, brief)
    report["executive_summary"] = (
        f"Day-30 checkpoint on Priority Introductions: the primary outcome is healthy at "
        f"{primary['difference_in_differences_pct']}% treatment vs control, inside the expected "
        f"band. Recorded feature adoption on Android/US falls "
        f"{abs(android_us['within_window']['second_vs_first_half_pct'])}% between the first and "
        f"second half of the window, but this is a measurement problem rather than a change in "
        f"user behaviour: priority_intro_sent completeness on Android/US is "
        f"{below['mean_completeness_pct']}% against a 95% floor, the event's schema version "
        f"changed inside the window, and the funnel step after it is unchanged. Recorded "
        f"adoption for Android/US is not usable evidence about users this period. Escalating "
        f"for measurement remediation before any adoption figure is reported onward."
    )
    report["segment_findings"] = [
        {
            "segment": "Android/US",
            "observation": (
                f"Recorded feature_adoption_rate in Android/US falls "
                f"{abs(android_us['within_window']['second_vs_first_half_pct'])}% half-over-half. "
                f"{contradiction['note']}"
            ),
            "arm_symmetry": (android_us.get("arm_symmetry") or {}).get("verdict"),
            "evidence_refs": [android_us["evidence_id"], contradiction["evidence_id"]],
            "confidence": "high",
            "limitations": (
                "The true adoption level for Android/US in the affected period is unknown and "
                "cannot be recovered from this data. Backfill would be required."
            ),
        }
    ]
    report["facts"] = [
        {
            "statement": (
                f"priority_intro_sent completeness on Android/US averages "
                f"{below['mean_completeness_pct']}% over the window against a 95% contract floor, "
                f"with the event's schema version changing inside the window."
            ),
            "evidence_refs": [below["evidence_id"]],
        },
        {
            "statement": contradiction["note"][:400],
            "evidence_refs": [contradiction["evidence_id"]],
        },
        {
            "statement": (
                f"Recorded feature_adoption_rate in Android/US is "
                f"{android_us['within_window']['second_vs_first_half_pct']}% in the second half of "
                f"the window relative to the first."
            ),
            "evidence_refs": [android_us["evidence_id"], breakdown["evidence_id"]],
        },
        {
            "statement": (
                f"mutual_connection_rate is {primary['difference_in_differences_pct']}% treatment "
                f"vs control, inside the contract's expected range."
            ),
            "evidence_refs": [primary["evidence_id"]],
        },
        {
            "statement": (
                "Release rel-1058 shipped an analytics SDK upgrade and event batching change to "
                "Android/US inside the checkpoint window."
            ),
            "evidence_refs": release_refs[:1] or [bundle["launch_context"][0]["evidence_id"]],
        },
    ]
    report["hypotheses"] = [
        {
            "statement": (
                "The priority_intro_sent event is under-reporting on Android/US, most likely "
                "introduced by the rel-1058 analytics SDK upgrade, which shipped to that segment "
                "inside the window."
            ),
            "supporting_evidence_refs": [
                below["evidence_id"],
                contradiction["evidence_id"],
            ]
            + release_refs[:1],
            "contradicting_evidence_refs": [],
            "confidence": "high",
            "how_to_test": (
                "Compare client event volume against server-side intro records for Android/US in "
                "the affected period; a gap confirms client under-reporting."
            ),
            "ruled_out": False,
        },
        {
            "statement": (
                "Android/US users could genuinely be sending fewer introductions, which would be "
                "a real adoption problem."
            ),
            "supporting_evidence_refs": [android_us["evidence_id"]],
            "contradicting_evidence_refs": [contradiction["evidence_id"]],
            "confidence": "low",
            "how_to_test": (
                "A genuine drop would reduce every downstream funnel step. The step after "
                "intro_sent is unchanged, which argues strongly against this."
            ),
            "ruled_out": True,
        },
    ]
    report["recommended_actions"] = [
        {
            "action": (
                "Treat Android/US adoption figures for this window as unreportable until "
                "priority_intro_sent is fixed and backfilled."
            ),
            "owner": "lifecycle-analytics",
            "rationale": (
                "Completeness below the contract floor means the metric measures the event, not "
                "the users."
            ),
            "blocks_product_decision": True,
            "evidence_refs": [below["evidence_id"]],
        },
        {
            "action": "Raise the priority_intro_sent schema change with the Android platform team, referencing rel-1058.",
            "owner": "product-discovery",
            "rationale": "The degradation begins with a release that shipped to exactly this segment.",
            "blocks_product_decision": False,
            "evidence_refs": release_refs[:1] or [bundle["launch_context"][0]["evidence_id"]],
        },
    ]
    report["confidence_and_escalation"] = {
        "overall_confidence": "medium",
        "escalate": True,
        "escalation_reasons": [
            f"priority_intro_sent completeness on Android/US is {below['mean_completeness_pct']}%, "
            f"below the 95% contract floor, so metrics derived from it are not trustworthy.",
            "Adoption reporting for Android/US must not go onward until measurement is repaired.",
        ],
        "escalation_route": brief["human_escalation_route"]["channel"],
    }
    return report


def case_04(bundle, brief, flawed: bool) -> dict:
    report = shell(bundle, brief)
    primary = movement(bundle, brief["primary_outcome"]["metric"])
    conversion = movement(bundle, "subscription_conversion_rate")
    android_gb = cell(bundle, "subscription_conversion_rate", "Android", "GB")
    breakdown = platform_market_breakdown(bundle, "subscription_conversion_rate")
    experiment_refs = context_refs(bundle, "exp-4502")
    symmetry = android_gb["arm_symmetry"]

    report["primary_outcome"] = primary_block(bundle, brief)

    if flawed:
        # The satisfying story. A real decline, a plausible feature, and a causal
        # claim the evidence cannot carry — while the report's own segment finding
        # records that control moved too.
        report["executive_summary"] = (
            f"Day-30 checkpoint on Priority Introductions: the primary outcome is healthy at "
            f"{primary['difference_in_differences_pct']}% treatment vs control. However, "
            f"subscription conversion in Android/GB fell "
            f"{abs(android_gb['relative_change_pct'])}% over the window. Priority Introductions "
            f"reduced subscription conversion for Android users in GB, most likely by diverting "
            f"attention from the paywall, and this is why the segment declined. Recommend "
            f"reviewing the paywall placement for Android/GB."
        )
        report["segment_findings"] = [
            {
                "segment": "Android/GB",
                "observation": (
                    f"subscription_conversion_rate in Android/GB fell "
                    f"{abs(android_gb['relative_change_pct'])}% over the window, "
                    f"{abs(android_gb['within_window']['second_vs_first_half_pct'])}% "
                    f"half-over-half, accounting for "
                    f"{android_gb['share_of_absolute_movement_pct']}% of total absolute movement."
                ),
                "arm_symmetry": symmetry["verdict"],
                "evidence_refs": [android_gb["evidence_id"], breakdown["evidence_id"]],
                "confidence": "high",
                "limitations": "Single market. Mechanism not directly observed.",
            }
        ]
        report["facts"] = [
            {
                "statement": (
                    f"subscription_conversion_rate in Android/GB fell "
                    f"{abs(android_gb['relative_change_pct'])}% over the checkpoint window."
                ),
                "evidence_refs": [android_gb["evidence_id"]],
            },
            {
                "statement": (
                    f"Aggregate subscription_conversion_rate is "
                    f"{conversion['difference_in_differences_pct']}% treatment vs control."
                ),
                "evidence_refs": [conversion["evidence_id"]],
            },
            {
                "statement": (
                    f"mutual_connection_rate is {primary['difference_in_differences_pct']}% "
                    f"treatment vs control, inside the contract's expected range."
                ),
                "evidence_refs": [primary["evidence_id"]],
            },
        ]
        report["hypotheses"] = [
            {
                "statement": (
                    "Priority Introductions diverted Android/GB users away from the paywall and "
                    "reduced conversion."
                ),
                "supporting_evidence_refs": [android_gb["evidence_id"]],
                "contradicting_evidence_refs": [],
                "confidence": "high",
                "how_to_test": "Compare paywall_viewed per active user in Android/GB treatment vs control.",
                "ruled_out": False,
            }
        ]
        report["recommended_actions"] = [
            {
                "action": "Review paywall placement for Android/GB with the monetization team.",
                "owner": "product-discovery",
                "rationale": "Conversion in the segment fell materially over the window.",
                "blocks_product_decision": False,
                "evidence_refs": [android_gb["evidence_id"]],
            }
        ]
        report["confidence_and_escalation"] = {
            "overall_confidence": "high",
            "escalate": False,
            "escalation_reasons": [],
            "escalation_route": None,
        }
        return report

    report["executive_summary"] = (
        f"Day-30 checkpoint on Priority Introductions: the primary outcome is healthy at "
        f"{primary['difference_in_differences_pct']}% treatment vs control. Subscription "
        f"conversion in Android/GB fell {abs(android_gb['relative_change_pct'])}% over the "
        f"window, and the decline is real — the funnel moves at checkout and stays down through "
        f"activation, and instrumentation is healthy. It cannot be attributed to Priority "
        f"Introductions: the movement appears in the control arm at "
        f"{symmetry['control_relative_change_pct']}% against "
        f"{symmetry['treatment_relative_change_pct']}% in treatment, and EXP-4502, a single-page "
        f"checkout redesign, is running on 60% of exactly this segment for exactly this period. "
        f"Two explanations remain live and this checkpoint cannot separate them. Escalating."
    )
    report["segment_findings"] = [
        {
            "segment": "Android/GB",
            "observation": (
                f"subscription_conversion_rate in Android/GB fell "
                f"{abs(android_gb['relative_change_pct'])}% over the window and "
                f"{abs(android_gb['within_window']['second_vs_first_half_pct'])}% half-over-half. "
                f"Treatment moved {symmetry['treatment_relative_change_pct']}% and control "
                f"{symmetry['control_relative_change_pct']}%. {symmetry['note']}"
            ),
            "arm_symmetry": symmetry["verdict"],
            "evidence_refs": [android_gb["evidence_id"], breakdown["evidence_id"]],
            "confidence": "high",
            "limitations": (
                "The overlapping experiment covers 60% of this cell, so the residual "
                "attributable to anything else cannot be isolated from this data alone."
            ),
        }
    ]
    report["facts"] = [
        {
            "statement": (
                f"subscription_conversion_rate in Android/GB fell "
                f"{abs(android_gb['relative_change_pct'])}% over the checkpoint window."
            ),
            "evidence_refs": [android_gb["evidence_id"]],
        },
        {
            "statement": (
                f"The Android/GB movement is present in both arms: "
                f"{symmetry['treatment_relative_change_pct']}% in treatment and "
                f"{symmetry['control_relative_change_pct']}% in control."
            ),
            "evidence_refs": [android_gb["evidence_id"]],
        },
        {
            "statement": (
                "EXP-4502, a single-page checkout redesign, is running on 60% of Android/GB free "
                "users across the whole checkpoint window, with subscription_conversion_rate as "
                "its own primary metric."
            ),
            "evidence_refs": experiment_refs[:1] or [bundle["launch_context"][-1]["evidence_id"]],
        },
        {
            "statement": (
                "Every critical event is above the 95% completeness floor in Android/GB, so the "
                "movement is not a measurement artefact."
            ),
            "evidence_refs": report["instrumentation_health"]["evidence_refs"][:1],
        },
        {
            "statement": (
                f"mutual_connection_rate is {primary['difference_in_differences_pct']}% treatment "
                f"vs control, inside the contract's expected range."
            ),
            "evidence_refs": [primary["evidence_id"]],
        },
    ]
    report["hypotheses"] = [
        {
            "statement": (
                "EXP-4502's checkout redesign may account for the Android/GB conversion decline; "
                "it covers 60% of the cell and targets the same metric."
            ),
            "supporting_evidence_refs": (experiment_refs[:1] or []) + [android_gb["evidence_id"]],
            "contradicting_evidence_refs": [],
            "confidence": "medium",
            "how_to_test": (
                "Split Android/GB by EXP-4502 assignment. If the decline is concentrated in its "
                "treatment cells, EXP-4502 is the explanation."
            ),
            "ruled_out": False,
        },
        {
            "statement": (
                "A market-level factor affecting all Android/GB users could explain the movement, "
                "since it is present in both arms of this experiment."
            ),
            "supporting_evidence_refs": [android_gb["evidence_id"]],
            "contradicting_evidence_refs": [],
            "confidence": "medium",
            "how_to_test": (
                "Check whether iOS/GB conversion moved over the same period. A market factor "
                "should not be confined to one platform."
            ),
            "ruled_out": False,
        },
        {
            "statement": (
                "Priority Introductions could have contributed to the decline by diverting "
                "attention from the paywall."
            ),
            "supporting_evidence_refs": [],
            "contradicting_evidence_refs": [android_gb["evidence_id"]],
            "confidence": "low",
            "how_to_test": (
                "A treatment-only effect would not appear in control. Control fell "
                f"{symmetry['control_relative_change_pct']}%, which largely rules this out as the "
                f"main driver."
            ),
            "ruled_out": True,
        },
    ]
    report["recommended_actions"] = [
        {
            "action": (
                "Do not attribute the Android/GB conversion decline to Priority Introductions in "
                "any onward reporting until EXP-4502 assignment is separated out."
            ),
            "owner": "lifecycle-analytics",
            "rationale": (
                "The movement is symmetric across arms and an overlapping experiment covers 60% "
                "of the cell. Attribution is not available from this checkpoint."
            ),
            "blocks_product_decision": True,
            "evidence_refs": [android_gb["evidence_id"]]
            + (experiment_refs[:1] or []),
        },
        {
            "action": "Split Android/GB conversion by EXP-4502 assignment with the monetization analytics owner.",
            "owner": "monetization-analytics",
            "rationale": "Cheapest test that would separate the two live explanations.",
            "blocks_product_decision": False,
            "evidence_refs": experiment_refs[:1] or [bundle["launch_context"][-1]["evidence_id"]],
        },
    ]
    report["confidence_and_escalation"] = {
        "overall_confidence": "medium",
        "escalate": True,
        "escalation_reasons": [
            "Two explanations for the Android/GB decline remain live at comparable confidence, "
            "and this checkpoint cannot separate them.",
            "EXP-4502 covers 60% of the affected segment, so clean attribution is unavailable.",
        ],
        "escalation_route": brief["human_escalation_route"]["channel"],
    }
    return report


def case_05(bundle, brief, flawed: bool) -> dict:
    report = shell(bundle, brief)
    primary = movement(bundle, brief["primary_outcome"]["metric"])
    absent = []
    for breakdowns in bundle["segment_breakdowns"].values():
        for breakdown in breakdowns:
            for entry in breakdown.get("segments_expected_but_absent", []):
                label = f"{entry['dimension']}={entry['value']}"
                if label not in absent:
                    absent.append(label)

    report["primary_outcome"] = primary_block(bundle, brief, override="not_measurable")
    report["executive_summary"] = (
        f"Day-30 checkpoint on Priority Introductions cannot be completed. Only "
        f"{bundle['window']['post_days_available']} of 30 checkpoint days and "
        f"{bundle['window']['pre_days_available']} of 30 pre-period days are present, so pre/post "
        f"comparisons are not like-for-like. {', '.join(absent)} is required by the launch "
        f"contract and absent from the metrics store entirely. There is no instrumentation "
        f"coverage for Android, so measurement integrity is unverified for half the target "
        f"platforms. Cell sizes are roughly two orders of magnitude below normal and every "
        f"observed movement is inside sampling noise at this scale. No conclusion about the "
        f"feature is supportable from this data. Escalating rather than reporting a result."
    )
    report["segment_findings"] = []
    report["facts"] = [
        {
            "statement": (
                f"The checkpoint window covers {bundle['window']['post_days_available']} of 30 "
                f"days and the pre-period {bundle['window']['pre_days_available']} of 30, so the "
                f"two periods are not comparable."
            ),
            "evidence_refs": [primary["evidence_id"]],
        },
        {
            "statement": (
                f"{', '.join(absent)} is required by the launch contract and has no rows in the "
                f"metrics store. This is missing data, not a zero."
            ),
            "evidence_refs": [
                platform_market_breakdown(bundle, brief["primary_outcome"]["metric"])["evidence_id"]
            ],
        },
        {
            "statement": (
                "There are no instrumentation records for Android in this window, so event "
                "completeness for that platform is unverified rather than healthy."
            ),
            "evidence_refs": report["instrumentation_health"]["evidence_refs"][:1]
            or [primary["evidence_id"]],
        },
    ]
    report["hypotheses"] = []
    report["recommended_actions"] = [
        {
            "action": (
                "Rerun this checkpoint once 30 full days, the DE market, and Android "
                "instrumentation coverage are present in the store."
            ),
            "owner": "lifecycle-analytics",
            "rationale": (
                "The inputs required by the launch contract are not available, so no reportable "
                "result exists yet."
            ),
            "blocks_product_decision": True,
            "evidence_refs": [primary["evidence_id"]],
        },
        {
            "action": "Confirm with the data platform owner why DE and Android instrumentation are absent.",
            "owner": "analytics-manager",
            "rationale": "A gap of this shape usually indicates a pipeline problem, not a genuine absence of users.",
            "blocks_product_decision": False,
            "evidence_refs": [primary["evidence_id"]],
        },
    ]
    report["confidence_and_escalation"] = {
        "overall_confidence": "low",
        "escalate": True,
        "escalation_reasons": [
            f"Checkpoint window incomplete: {bundle['window']['post_days_available']} of 30 days.",
            f"Required segment absent from the metrics store: {', '.join(absent)}.",
            "No instrumentation coverage for Android; measurement integrity unverified.",
        ],
        "escalation_route": brief["human_escalation_route"]["channel"],
    }
    return report


def primary_scenario(bundle, brief, flawed: bool = False) -> dict:
    """The reference report for the live workshop scenario.

    Shipped in solutions/checkpoint-1/ rather than reports/ so participants still do
    the work, and facilitators still have the expected output to read from when a
    live run misbehaves.
    """
    report = shell(bundle, brief)
    primary = movement(bundle, brief["primary_outcome"]["metric"])
    adoption = movement(bundle, "feature_adoption_rate")
    conversion = movement(bundle, "subscription_conversion_rate")
    android_gb = cell(bundle, "subscription_conversion_rate", "Android", "GB")
    breakdown = platform_market_breakdown(bundle, "subscription_conversion_rate")
    instrumentation = bundle["instrumentation"]
    below = next(
        e for e in instrumentation["below_floor"] if e["event"] == "payment_completed"
    )
    contradiction = next(
        c for c in funnel_contradictions(bundle) if c["filters"].get("market") == "GB"
    )
    release_refs = context_refs(bundle, "rel-1062")
    symmetry = android_gb["arm_symmetry"]
    payment_guardrail = next(
        g for g in bundle["guardrail_status"]["guardrails"]
        if g["metric"] == "payment_completion_rate"
    )

    report["primary_outcome"] = primary_block(bundle, brief)
    report["executive_summary"] = (
        f"Day-30 checkpoint on Priority Introductions. The feature is performing as "
        f"intended: adoption among eligible treatment users is "
        f"{round((adoption.get('treatment', {}).get('value') or 0) * 100, 1)}% and the "
        f"primary outcome, mutual_connection_rate, is "
        f"{primary['difference_in_differences_pct']}% higher in treatment than control, "
        f"inside the contract's expected band. Separately, the payment_completion_rate "
        f"guardrail is breached in Android/GB. That breach is a measurement failure, not "
        f"a revenue event: the payment_completed event is under-reporting on Android/GB "
        f"at {below['mean_completeness_pct']}% completeness against a 95% floor, "
        f"server-side subscription activations are unchanged, and observed activations "
        f"now exceed observed payments, which is not possible. The movement also appears "
        f"in the control arm, so Priority Introductions cannot be its cause. Escalating "
        f"on the guardrail breach. No rollback is warranted; the GB conversion figures "
        f"for this window must not be reported onward until the event is repaired."
    )
    report["segment_findings"] = [
        {
            "segment": "Android/GB",
            "observation": (
                f"Recorded subscription_conversion_rate in Android/GB fell "
                f"{abs(android_gb['relative_change_pct'])}% over the window and "
                f"{abs(android_gb['within_window']['second_vs_first_half_pct'])}% "
                f"half-over-half, accounting for "
                f"{android_gb['share_of_absolute_movement_pct']}% of total absolute "
                f"movement. Treatment moved {symmetry['treatment_relative_change_pct']}% "
                f"and control {symmetry['control_relative_change_pct']}%. "
                f"{symmetry['note']}"
            ),
            "arm_symmetry": symmetry["verdict"],
            "evidence_refs": [android_gb["evidence_id"], breakdown["evidence_id"]],
            "confidence": "high",
            "limitations": (
                "True conversion for Android/GB during the affected period is unknown "
                "from this data. Reconciliation against processor records would be "
                "needed to quantify any real revenue impact."
            ),
        }
    ]
    report["facts"] = [
        {
            "statement": (
                f"mutual_connection_rate is {primary['difference_in_differences_pct']}% "
                f"higher in treatment than control, inside the contract's expected "
                f"2.0-4.0% band."
            ),
            "evidence_refs": [primary["evidence_id"]],
        },
        {
            "statement": (
                f"Aggregate subscription_conversion_rate moved "
                f"{conversion['pre_post_relative_pct']}% pre/post, which is why the "
                f"Android/GB movement is invisible without segmentation."
            ),
            "evidence_refs": [conversion["evidence_id"]],
        },
        {
            "statement": (
                f"Recorded subscription_conversion_rate in Android/GB fell "
                f"{abs(android_gb['relative_change_pct'])}% over the window, present in "
                f"both arms at {symmetry['treatment_relative_change_pct']}% treatment "
                f"and {symmetry['control_relative_change_pct']}% control."
            ),
            "evidence_refs": [android_gb["evidence_id"]],
        },
        {
            "statement": (
                f"payment_completed completeness on Android/GB averages "
                f"{below['mean_completeness_pct']}% against a 95% contract floor, with "
                f"schema version changing from 4 to 5 inside the window and the null "
                f"rate on a required property reaching "
                f"{round(below['worst_null_rate_key_property'] * 100, 1)}%."
            ),
            "evidence_refs": [below["evidence_id"]],
        },
        {
            "statement": contradiction["note"][:400],
            "evidence_refs": [contradiction["evidence_id"]],
        },
        {
            "statement": (
                "Release rel-1062 shipped Android 9.42.0 to GB only on 2026-05-18 as a "
                "staged rollout, including a billing client upgrade, and reaches the "
                "affected segment."
            ),
            "evidence_refs": release_refs[:1] or [bundle["launch_context"][-1]["evidence_id"]],
        },
        {
            "statement": (
                f"The payment_completion_rate guardrail is breached in Android/GB while "
                f"passing in aggregate at "
                f"{payment_guardrail['aggregate']['relative_change_pct']}%."
            ),
            "evidence_refs": [payment_guardrail["evidence_id"]],
        },
    ]
    report["hypotheses"] = [
        {
            "statement": (
                "The billing client upgrade in rel-1062 may have broken payment_completed "
                "reporting on Android/GB, making conversion and payment completion appear "
                "to fall while purchasing continued normally."
            ),
            "supporting_evidence_refs": [
                below["evidence_id"],
                contradiction["evidence_id"],
                android_gb["evidence_id"],
            ] + release_refs[:1],
            "contradicting_evidence_refs": [],
            "confidence": "high",
            "how_to_test": (
                "Reconcile client payment_completed events against payment processor "
                "records for Android/GB from 2026-05-18. A gap confirms client-side "
                "under-reporting and quantifies the real impact."
            ),
            "ruled_out": False,
        },
        {
            "statement": (
                "Android/GB users could genuinely have stopped completing payments, which "
                "would be a real revenue problem."
            ),
            "supporting_evidence_refs": [android_gb["evidence_id"]],
            "contradicting_evidence_refs": [contradiction["evidence_id"]],
            "confidence": "low",
            "how_to_test": (
                "A genuine drop would reduce subscription_activated, which is recorded "
                "server-side. It did not move, and observed activations now exceed "
                "observed payments. This is ruled out."
            ),
            "ruled_out": True,
        },
        {
            "statement": (
                "Priority Introductions could have suppressed conversion for Android/GB "
                "users."
            ),
            "supporting_evidence_refs": [],
            "contradicting_evidence_refs": [android_gb["evidence_id"]],
            "confidence": "low",
            "how_to_test": (
                "A treatment-only feature cannot move the control arm. Control fell "
                f"{symmetry['control_relative_change_pct']}%, essentially the same as "
                f"treatment. This is ruled out."
            ),
            "ruled_out": True,
        },
    ]
    report["recommended_actions"] = [
        {
            "action": (
                "Do not report Android/GB conversion or payment completion figures for "
                "this window onward, and do not treat the guardrail breach as a revenue "
                "event."
            ),
            "owner": "lifecycle-analytics",
            "rationale": (
                "The metrics are derived from an event at "
                f"{below['mean_completeness_pct']}% completeness. They describe the event, "
                f"not the users."
            ),
            "blocks_product_decision": True,
            "evidence_refs": [below["evidence_id"], contradiction["evidence_id"]],
        },
        {
            "action": (
                "Raise rel-1062's billing client upgrade with the Android platform team "
                "and hold the staged rollout to remaining markets."
            ),
            "owner": "product-discovery",
            "rationale": (
                "The degradation begins on the day a payment-touching build shipped to GB "
                "alone. Shipping it further would extend the measurement gap."
            ),
            "blocks_product_decision": True,
            "evidence_refs": release_refs[:1] or [bundle["launch_context"][-1]["evidence_id"]],
        },
        {
            "action": (
                "Reconcile client payment events against processor records for Android/GB "
                "from 2026-05-18 to quantify any real impact."
            ),
            "owner": "monetization-analytics",
            "rationale": "The only test that separates a reporting gap from lost revenue.",
            "blocks_product_decision": False,
            "evidence_refs": [below["evidence_id"]],
        },
    ]
    report["confidence_and_escalation"] = {
        "overall_confidence": "medium",
        "escalate": True,
        "escalation_reasons": [
            f"payment_completion_rate guardrail breached in Android/GB "
            f"({payment_guardrail['status']}).",
            f"payment_completed completeness on Android/GB is "
            f"{below['mean_completeness_pct']}%, below the 95% contract floor, so "
            f"subscription_conversion_rate and payment_completion_rate are not "
            f"trustworthy in that cell.",
            "A decision on the remaining staged rollout of rel-1062 is required.",
        ],
        "escalation_route": brief["human_escalation_route"]["channel"],
    }
    return report


BUILDERS = {
    "01-healthy-launch": case_01,
    "02-real-segment-decline": case_02,
    "03-instrumentation-failure": case_03,
    "04-confounded-result": case_04,
    "05-insufficient-evidence": case_05,
}


def main() -> None:
    brief = _yaml.load_path(BRIEF_PATH)
    SOLUTION_DIR.mkdir(parents=True, exist_ok=True)

    for case_name, builder in BUILDERS.items():
        case_dir = CASES_DIR / case_name
        case = _yaml.load_path(case_dir / "case.yaml")
        bundle = run_checkpoint.build(
            str(BRIEF_PATH), int(case.get("checkpoint", 30)), case.get("data_dir")
        )

        for flawed, destination in (
            (True, case_dir / "baseline_report.json"),
            (False, SOLUTION_DIR / f"{case_name}.json"),
        ):
            report = builder(bundle, brief, flawed)
            report["evidence_index"] = build_evidence_index(report)
            destination.write_text(
                json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
            )
        print(f"{case_name}: baseline + solution written")

    # The reference report for the live workshop scenario.
    bundle = run_checkpoint.build(str(BRIEF_PATH), 30, None)
    reference = primary_scenario(bundle, brief)
    reference["evidence_index"] = build_evidence_index(reference)
    destination = REPO_ROOT / "solutions" / "checkpoint-1" / "reference-report.json"
    destination.write_text(json.dumps(reference, indent=2, default=str) + "\n", encoding="utf-8")
    print("primary scenario: solutions/checkpoint-1/reference-report.json written")


if __name__ == "__main__":
    main()
