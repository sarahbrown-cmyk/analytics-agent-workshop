#!/usr/bin/env python3
"""Enforce the report contract.

A monitoring report is not finished when it reads well. It is finished when it
passes this file. Five layers, in order of how easily a fluent model can talk its
way past them:

1. **Schema** — the ten required sections exist and have the right shape.
2. **Evidence** — every cited evidence id was actually produced by a tool run.
   Citing `EV-SEG-something-plausible` that no tool emitted is caught here.
3. **Deterministic rubric** — the rubric checks marked `deterministic: true` in
   src/reviewers/review_rubric.yaml, applied as code.
4. **Causal discipline** — src/reviewers/causal_language.py.
5. **Escalation** — the rules in src/schemas/escalation_rules.yaml are evaluated
   against the evidence bundle, and the report's own escalate flag must agree.
   The agent does not get to decide whether it feels confident enough.

Usage:
    python3 src/coordinator/report_contract.py reports/priority-recommendations-day30.json
    python3 src/coordinator/report_contract.py <report.json> --evidence <bundle.json>
    python3 src/coordinator/report_contract.py <report.json> --render
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from reviewers import causal_language  # noqa: E402
from schemas import _validate  # noqa: E402
from tools import _yaml, metric_definitions  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "src" / "schemas" / "monitoring_report.schema.json"
ESCALATION_RULES_PATH = REPO_ROOT / "src" / "schemas" / "escalation_rules.yaml"
RUBRIC_PATH = REPO_ROOT / "src" / "reviewers" / "review_rubric.yaml"
DEFAULT_BRIEF = REPO_ROOT / "feature_briefs" / "priority-recommendations.yaml"

# Tolerance when comparing a number in the report against the tool output it cites.
NUMERIC_TOLERANCE_PCT = 0.15


# ---------------------------------------------------------------------------
# Escalation checks. Implemented here; switched on in escalation_rules.yaml.
# ---------------------------------------------------------------------------


def _check_guardrail_breach(report, bundle, brief):
    status = (bundle or {}).get("guardrail_status") or {}
    if status.get("escalation_required"):
        return status.get("escalation_reason") or "A guardrail breached its threshold."
    return None


def _check_required_segment_missing(report, bundle, brief):
    absent = []
    for breakdowns in ((bundle or {}).get("segment_breakdowns") or {}).values():
        for breakdown in breakdowns:
            for entry in breakdown.get("segments_expected_but_absent", []):
                label = f"{entry['dimension']}={entry['value']}"
                if label not in absent:
                    absent.append(label)
    if absent:
        return "Required segment(s) absent from the metrics store: " + ", ".join(absent)
    return None


def _check_window_incomplete(report, bundle, brief):
    window = (bundle or {}).get("window") or {}
    if window and not window.get("complete", True):
        return "; ".join(window.get("notes") or ["Checkpoint window incomplete."])
    return None


def _check_competing_explanations_unresolved(report, bundle, brief):
    live = [
        h
        for h in report.get("hypotheses", [])
        if not h.get("ruled_out") and (h.get("confidence") or "").lower() in ("medium", "high")
    ]
    if len(live) >= 2:
        return (
            f"{len(live)} explanations remain live at medium or high confidence: "
            + "; ".join(h.get("statement", "")[:80] for h in live)
        )
    return None


def _check_sample_below_mde(report, bundle, brief):
    primary_metric = brief["primary_outcome"]["metric"]
    for entry in (bundle or {}).get("metric_movement", []):
        if entry["metric"] == primary_metric and entry.get("exceeds_mde") is False:
            return (
                f"{primary_metric} movement of "
                f"{entry.get('difference_in_differences_pct')}% does not clear the "
                f"{entry.get('minimum_detectable_effect_pct')}% minimum detectable effect."
            )
    return None


def _check_claim_without_evidence(report, bundle, brief):
    produced = set((bundle or {}).get("evidence_ids") or [])
    problems = []
    for index, fact in enumerate(report.get("facts", [])):
        refs = fact.get("evidence_refs") or []
        if not refs:
            problems.append(f"facts[{index}] has no evidence reference")
            continue
        for ref in refs:
            if produced and ref not in produced:
                problems.append(f"facts[{index}] cites {ref}, which no tool produced")
    if problems:
        return "; ".join(problems[:6])
    return None


def _check_instrumentation_below_floor(report, bundle, brief):
    instrumentation = (bundle or {}).get("instrumentation")
    if instrumentation is None:
        return (
            "No instrumentation data available for this run, so measurement "
            "integrity is unverified."
        )
    below = instrumentation.get("below_floor") or []
    gaps = instrumentation.get("coverage_gaps") or []
    if below or gaps:
        parts = [
            f"{entry['event']} on {entry['platform']}/{entry['market']} at "
            f"{entry['mean_completeness_pct']}%"
            for entry in below
        ] + [f"no coverage for {g['event']} on {g['platform']}/{g['market']}" for g in gaps]
        return "Instrumentation below the contract floor: " + "; ".join(parts[:6])
    return None


ESCALATION_CHECKS = {
    "guardrail_breach": _check_guardrail_breach,
    "required_segment_missing": _check_required_segment_missing,
    "window_incomplete": _check_window_incomplete,
    "competing_explanations_unresolved": _check_competing_explanations_unresolved,
    "sample_below_mde": _check_sample_below_mde,
    "claim_without_evidence": _check_claim_without_evidence,
    "instrumentation_below_floor": _check_instrumentation_below_floor,
}


def evaluate_escalation(report, bundle, brief) -> dict:
    rules = _yaml.load_path(ESCALATION_RULES_PATH).get("rules", [])
    enabled = [r for r in rules if r.get("enabled", True)]
    enabled_ids = {r["id"] for r in enabled}

    fired = []
    for rule in enabled:
        check = ESCALATION_CHECKS.get(rule["id"])
        if check is None:
            continue
        detail = check(report, bundle, brief)
        if detail:
            fired.append(
                {
                    "rule": rule["id"],
                    "severity": rule.get("severity", "high"),
                    "detail": detail,
                    "reason": (rule.get("reason") or "").strip(),
                }
            )

    # Checks that would have fired if the rule were switched on. Reported, not
    # enforced — the point is to make an unenforced trigger visible instead of
    # invisible.
    contract_triggers = set(brief.get("escalation_triggers") or [])
    dormant = []
    for rule_id, check in ESCALATION_CHECKS.items():
        if rule_id in enabled_ids:
            continue
        detail = check(report, bundle, brief)
        if detail:
            dormant.append(
                {
                    "rule": rule_id,
                    "detail": detail,
                    "in_launch_contract": rule_id in contract_triggers,
                }
            )

    required = bool(fired)
    reported = bool((report.get("confidence_and_escalation") or {}).get("escalate"))
    return {
        "rules_enabled": sorted(enabled_ids),
        "rules_implemented_but_disabled": sorted(set(ESCALATION_CHECKS) - enabled_ids),
        "fired": fired,
        "would_have_fired_if_enabled": dormant,
        "escalation_required": required,
        "escalation_reported": reported,
        "agrees": required == reported,
        "verdict": (
            "correct"
            if required == reported
            else ("under_escalated" if required and not reported else "over_escalated")
        ),
    }


# ---------------------------------------------------------------------------
# Deterministic rubric checks
# ---------------------------------------------------------------------------


def deterministic_rubric(report, bundle, brief) -> list[dict]:
    rubric = _yaml.load_path(RUBRIC_PATH).get("checks", [])
    active = {c["id"]: c for c in rubric if c.get("deterministic")}
    results = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        if check_id not in active:
            return
        results.append(
            {
                "check": check_id,
                "severity": active[check_id].get("severity", "warning"),
                "passed": passed,
                "detail": detail,
            }
        )

    # metric_definitions_correct
    named = {report.get("primary_outcome", {}).get("metric")}
    named |= {item.get("metric") for item in report.get("guardrail_status", {}).get("items", [])}
    named.discard(None)
    undefined = sorted(m for m in named if metric_definitions.get(m) is None)
    record(
        "metric_definitions_correct",
        not undefined,
        "All reported metrics have governed definitions."
        if not undefined
        else f"No governed definition for: {', '.join(undefined)}.",
    )

    # required_segments_covered
    required = [str(s) for s in brief.get("required_segments", [])]
    checked = {str(s).strip().lower() for s in report.get("segments_checked", [])}
    missing = [s for s in required if s.strip().lower() not in checked]
    record(
        "required_segments_covered",
        not missing,
        "Every contract-required segment is listed as checked."
        if not missing
        else (
            f"segments_checked does not account for: {', '.join(missing)}. A reader "
            f"cannot tell whether these were examined and found unremarkable."
        ),
    )

    # evidence_completeness
    produced = set((bundle or {}).get("evidence_ids") or [])
    indexed = {e.get("evidence_id") for e in report.get("evidence_index", [])}
    cited = _all_cited_refs(report)
    unproduced = sorted(r for r in cited if produced and r not in produced)
    unindexed = sorted(r for r in cited if r not in indexed)
    evidence_ok = not unproduced and not unindexed
    record(
        "evidence_completeness",
        evidence_ok,
        "Every citation is real and indexed."
        if evidence_ok
        else "; ".join(
            filter(
                None,
                [
                    f"cited but not produced by any tool: {', '.join(unproduced[:5])}" if unproduced else "",
                    f"cited but missing from evidence_index: {', '.join(unindexed[:5])}" if unindexed else "",
                ],
            )
        ),
    )

    # numerical_consistency — the primary outcome figure against the tool output
    consistency_detail = "Primary outcome figure matches the cited tool output."
    consistent = True
    reported_value = report.get("primary_outcome", {}).get("treatment_vs_control_relative_pct")
    primary_metric = brief["primary_outcome"]["metric"]
    for entry in (bundle or {}).get("metric_movement", []):
        if entry["metric"] != primary_metric:
            continue
        truth = entry.get("difference_in_differences_pct")
        if reported_value is None or truth is None:
            continue
        if abs(float(reported_value) - float(truth)) > NUMERIC_TOLERANCE_PCT:
            consistent = False
            consistency_detail = (
                f"Report states {reported_value}% for {primary_metric}; the tool "
                f"produced {truth}%."
            )
    record("numerical_consistency", consistent, consistency_detail)

    # instrumentation_awareness
    untrusted = set(((bundle or {}).get("instrumentation") or {}).get("metrics_not_trustworthy") or [])
    instrumentation_status = report.get("instrumentation_health", {}).get("status")
    aware = True
    detail = "No metric is compromised by instrumentation, or the report says so."
    if untrusted:
        if instrumentation_status in ("healthy", None):
            aware = False
            detail = (
                f"Instrumentation compromises {', '.join(sorted(untrusted))}, but the "
                f"report records instrumentation_health.status={instrumentation_status!r}."
            )
        else:
            declared = set(report.get("instrumentation_health", {}).get("metrics_not_trustworthy") or [])
            unlisted = sorted(untrusted - declared)
            if unlisted:
                aware = False
                detail = (
                    f"Report does not list these as untrustworthy: {', '.join(unlisted)}."
                )
    record("instrumentation_awareness", aware, detail)

    # alternative_explanations_engaged — every candidate the context tool surfaced
    # for a focus cell must appear somewhere in the report, either kept live with a
    # test or explicitly ruled out.
    available = _available_explanations(bundle)
    prose = _report_prose(report).lower()
    unmentioned = sorted(ref for ref in available if ref.lower() not in prose)
    record(
        "alternative_explanations_engaged",
        not unmentioned,
        "Every competing explanation in the evidence is named in the report."
        if not unmentioned
        else (
            f"Present in the evidence and never mentioned: {', '.join(unmentioned)}. "
            f"A single explanation with no rejected alternatives has narrated rather "
            f"than investigated."
        ),
    )

    # causal_discipline is enforced by src/reviewers/causal_language.py, which runs
    # as its own layer. Recorded here so the rubric item is visibly backed.
    causal = causal_language.review(report)
    record(
        "causal_discipline",
        causal["passed"],
        "No blocking causal violations."
        if causal["passed"]
        else "; ".join(
            f"{v['check']} at {v['location']}"
            for v in causal["violations"]
            if v["severity"] == "blocking"
        ),
    )

    # A rubric check marked deterministic with nothing implementing it is worse than
    # no check at all: it creates the appearance of a control. Say so out loud.
    implemented = {r["check"] for r in results}
    for check_id in sorted(set(active) - implemented):
        results.append(
            {
                "check": check_id,
                "severity": "warning",
                "passed": True,
                "detail": (
                    "marked deterministic: true in the rubric, but no check in "
                    "report_contract.py enforces it. It is currently decoration — "
                    "either implement it or set deterministic: false."
                ),
            }
        )

    return results


def _available_explanations(bundle: dict | None) -> set[str]:
    """Candidate explanations the context tool found for a focus segment.

    Only the ones that actually reach the affected cell. A release that never
    shipped to the segment is not an explanation the report owes anyone.
    """
    found: set[str] = set()
    for context in (bundle or {}).get("launch_context", []) or []:
        focus = context.get("focus_segment") or {}
        if not focus.get("platform") and not focus.get("market"):
            continue
        found.update(context.get("potentially_confounding_experiments") or [])
        for release in context.get("releases_in_window", []):
            if release.get("dimension_match", {}).get("reaches_focus_segment") and release.get(
                "touches_payments"
            ):
                found.add(release["release_id"])
    return found


def _report_prose(report: dict) -> str:
    chunks = [report.get("executive_summary", "") or ""]
    for key in ("facts", "hypotheses"):
        for entry in report.get(key, []):
            chunks.append(entry.get("statement", "") or "")
    for finding in report.get("segment_findings", []):
        chunks.append(finding.get("observation", "") or "")
    for action in report.get("recommended_actions", []):
        chunks.append(action.get("action", "") or "")
        chunks.append(action.get("rationale", "") or "")
    for reason in (report.get("confidence_and_escalation") or {}).get("escalation_reasons", []):
        chunks.append(reason)
    return "\n".join(chunks)


def _all_cited_refs(report) -> set[str]:
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("evidence_refs") and isinstance(value, list):
                    found.update(v for v in value if isinstance(v, str))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(report)
    return found


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def validate_report(report: dict, bundle: dict | None, brief: dict) -> dict:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_errors = _validate.validate(report, schema)
    rubric_results = deterministic_rubric(report, bundle, brief)
    causal = causal_language.review(report)
    escalation = evaluate_escalation(report, bundle, brief)

    blocking_rubric = [r for r in rubric_results if not r["passed"] and r["severity"] == "blocking"]

    passed = (
        not schema_errors
        and not blocking_rubric
        and causal["passed"]
        and escalation["agrees"]
    )

    return {
        "report_feature_id": report.get("feature_id"),
        "checkpoint_days": report.get("checkpoint_days"),
        "schema_errors": schema_errors,
        "deterministic_rubric": rubric_results,
        "causal_review": causal,
        "escalation": escalation,
        "blocking_failures": (
            [f"schema: {e}" for e in schema_errors]
            + [f"rubric/{r['check']}: {r['detail']}" for r in blocking_rubric]
            + [
                f"causal/{v['check']} at {v['location']}: {v['why']}"
                for v in causal["violations"]
                if v["severity"] == "blocking"
            ]
            + (
                [f"escalation: {escalation['verdict']}"]
                if not escalation["agrees"]
                else []
            )
        ),
        "passed": passed,
    }


def render_markdown(report: dict) -> str:
    """The human-readable version. Generated, never hand-written.

    Deriving the prose from the validated structure means the document a
    stakeholder reads cannot drift from the document the gate checked.
    """
    out: list[str] = []
    escalation = report.get("confidence_and_escalation", {})
    window = report.get("window", {})

    out.append(f"# {report.get('feature_id')} — day-{report.get('checkpoint_days')} checkpoint")
    out.append("")
    out.append(
        f"*Window {window.get('post_start')} to {window.get('post_end')} against "
        f"{window.get('pre_start')} to {window.get('pre_end')}. "
        f"Contract version {report.get('brief_version')}. "
        f"Confidence: {escalation.get('overall_confidence')}. "
        f"Escalation: {'REQUIRED' if escalation.get('escalate') else 'not required'}.*"
    )
    out.append("")
    out.append("## 1. Executive summary")
    out.append("")
    out.append(report.get("executive_summary", ""))
    out.append("")

    primary = report.get("primary_outcome", {})
    out.append("## 2. Primary outcome")
    out.append("")
    out.append(
        f"- **{primary.get('metric')}**: {primary.get('treatment_vs_control_relative_pct')}% "
        f"treatment vs control — *{primary.get('verdict')}*"
    )
    out.append(f"- Evidence: {', '.join(primary.get('evidence_refs', [])) or 'none'}")
    out.append("")

    guardrails = report.get("guardrail_status", {})
    out.append(f"## 3. Guardrail status — {guardrails.get('overall', 'unknown').upper()}")
    out.append("")
    out.append("| Metric | Status | Worst segment | Evidence |")
    out.append("|---|---|---|---|")
    for item in guardrails.get("items", []):
        out.append(
            f"| {item.get('metric')} | {item.get('status')} | "
            f"{item.get('worst_segment') or '—'} | "
            f"{', '.join(item.get('evidence_refs', [])) or '—'} |"
        )
    out.append("")

    out.append("## 4. Segment findings")
    out.append("")
    if not report.get("segment_findings"):
        out.append("No segment-level findings.")
    for finding in report.get("segment_findings", []):
        out.append(f"### {finding.get('segment')}")
        out.append("")
        out.append(finding.get("observation", ""))
        out.append("")
        out.append(f"- Arm symmetry: `{finding.get('arm_symmetry')}`")
        out.append(f"- Confidence: {finding.get('confidence')}")
        out.append(f"- Limitations: {finding.get('limitations')}")
        out.append(f"- Evidence: {', '.join(finding.get('evidence_refs', [])) or 'none'}")
        out.append("")

    if report.get("segments_checked"):
        out.append("**Segments checked:** " + ", ".join(report["segments_checked"]))
        out.append("")

    instrumentation = report.get("instrumentation_health", {})
    out.append(f"## 5. Instrumentation health — {instrumentation.get('status', 'unknown').upper()}")
    out.append("")
    if instrumentation.get("events_below_floor"):
        out.append("- Events below floor: " + ", ".join(instrumentation["events_below_floor"]))
    if instrumentation.get("metrics_not_trustworthy"):
        out.append(
            "- Metrics not trustworthy in affected cells: "
            + ", ".join(instrumentation["metrics_not_trustworthy"])
        )
    out.append(f"- Evidence: {', '.join(instrumentation.get('evidence_refs', [])) or 'none'}")
    out.append("")

    out.append("## 6. Facts supported by evidence")
    out.append("")
    for fact in report.get("facts", []):
        out.append(f"- {fact.get('statement')} `[{', '.join(fact.get('evidence_refs', []))}]`")
    out.append("")

    out.append("## 7. Open hypotheses")
    out.append("")
    for hypothesis in report.get("hypotheses", []):
        state = " *(ruled out)*" if hypothesis.get("ruled_out") else ""
        out.append(f"- **{hypothesis.get('statement')}**{state}")
        out.append(f"  - Confidence: {hypothesis.get('confidence')}")
        if hypothesis.get("supporting_evidence_refs"):
            out.append(f"  - Supported by: {', '.join(hypothesis['supporting_evidence_refs'])}")
        if hypothesis.get("contradicting_evidence_refs"):
            out.append(f"  - Argued against by: {', '.join(hypothesis['contradicting_evidence_refs'])}")
        out.append(f"  - How to test: {hypothesis.get('how_to_test')}")
    out.append("")

    out.append("## 8. Recommended next actions")
    out.append("")
    for action in report.get("recommended_actions", []):
        flag = " **(blocks a product decision)**" if action.get("blocks_product_decision") else ""
        out.append(f"- {action.get('action')} — *{action.get('owner')}*{flag}")
        out.append(f"  - Rationale: {action.get('rationale')}")
    out.append("")

    out.append("## 9. Confidence and escalation")
    out.append("")
    out.append(f"- Overall confidence: **{escalation.get('overall_confidence')}**")
    out.append(f"- Escalate: **{'yes' if escalation.get('escalate') else 'no'}**")
    for reason in escalation.get("escalation_reasons", []):
        out.append(f"  - {reason}")
    if escalation.get("escalation_route"):
        out.append(f"- Route: {escalation['escalation_route']}")
    out.append("")

    out.append("## 10. Evidence index")
    out.append("")
    out.append("| Evidence id | Tool | Summary |")
    out.append("|---|---|---|")
    for entry in report.get("evidence_index", []):
        out.append(
            f"| `{entry.get('evidence_id')}` | {entry.get('tool')} | {entry.get('summary', '')} |"
        )
    out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="Path to a monitoring report JSON file.")
    parser.add_argument("--evidence", help="Path to the evidence bundle JSON.")
    parser.add_argument("--brief", default=str(DEFAULT_BRIEF))
    parser.add_argument("--render", action="store_true", help="Print markdown instead of validating.")
    parser.add_argument("--quiet", action="store_true", help="Print only the verdict line.")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    if not report_path.exists():
        sys.stderr.write(f"error: report not found: {report_path}\n")
        raise SystemExit(2)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    if args.render:
        print(render_markdown(report))
        return

    bundle = None
    if args.evidence:
        bundle_path = Path(args.evidence)
        if not bundle_path.is_absolute():
            bundle_path = REPO_ROOT / bundle_path
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    brief = _yaml.load_path(args.brief)
    result = validate_report(report, bundle, brief)

    if args.quiet:
        print("PASS" if result["passed"] else "FAIL")
    else:
        print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
