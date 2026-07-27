"""Deterministic scorers, one per rubric dimension.

Each scorer takes the report, the evidence bundle for the case, the launch
contract, and the case's expectations, and returns `(passed, score, detail)`.

They are deterministic on purpose. An evaluation suite that uses a model to grade
a model gives you two things to debug instead of one, drifts between runs, and
cannot be put in a pre-commit gate. Every dimension here is either arithmetic or a
set comparison, which means the scorecard is the same for everyone in the room and
the same next month.

The cost of that choice is honest and worth stating: these scorers check whether
the report did the work, not whether the prose is good. Judging the writing is a
human's job, and `uncertainty_calibration` is the closest any of them get.
"""

from __future__ import annotations

import re
from typing import Any

Result = tuple[bool, float, str]

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _normalise_segment(text: str) -> str:
    """'Android / GB', 'android-gb', 'Android/GB' all compare equal."""
    return "".join(c for c in (text or "").lower() if c.isalnum())


def _report_text(report: dict) -> str:
    """All prose in the report, for phrase checks."""
    chunks = [report.get("executive_summary", "") or ""]
    for fact in report.get("facts", []):
        chunks.append(fact.get("statement", "") or "")
    for hypothesis in report.get("hypotheses", []):
        chunks.append(hypothesis.get("statement", "") or "")
    for finding in report.get("segment_findings", []):
        chunks.append(finding.get("observation", "") or "")
    for action in report.get("recommended_actions", []):
        chunks.append(action.get("action", "") or "")
        chunks.append(action.get("rationale", "") or "")
    return "\n".join(chunks).lower()


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


def metric_correctness(report, bundle, brief, expect, contract) -> Result:
    from tools import metric_definitions

    contract_metric = brief["primary_outcome"]["metric"]
    reported_metric = report.get("primary_outcome", {}).get("metric")
    problems = []
    if reported_metric != contract_metric:
        problems.append(
            f"primary outcome is {reported_metric!r}; the contract names {contract_metric!r}"
        )

    named = {reported_metric}
    named |= {i.get("metric") for i in report.get("guardrail_status", {}).get("items", [])}
    named.discard(None)
    undefined = sorted(m for m in named if metric_definitions.get(m) is None)
    if undefined:
        problems.append(f"no governed definition for {', '.join(undefined)}")

    contract_guardrails = {g["metric"] for g in brief.get("guardrail_metrics", [])}
    reported_guardrails = {i.get("metric") for i in report.get("guardrail_status", {}).get("items", [])}
    missing = sorted(contract_guardrails - reported_guardrails)
    if missing:
        problems.append(f"contract guardrails not reported: {', '.join(missing)}")

    if problems:
        return False, 0.0, "; ".join(problems)
    return True, 1.0, f"Primary outcome {contract_metric}; all guardrails reported with definitions."


def numerical_correctness(report, bundle, brief, expect, contract) -> Result:
    tolerance = 0.15
    primary_metric = brief["primary_outcome"]["metric"]
    truth = None
    for entry in bundle.get("metric_movement", []):
        if entry["metric"] == primary_metric:
            truth = entry.get("difference_in_differences_pct")
    reported = report.get("primary_outcome", {}).get("treatment_vs_control_relative_pct")

    if truth is None:
        return True, 1.0, "No tool figure available to compare against."
    if reported is None:
        return False, 0.0, f"Report gives no figure for {primary_metric}; tool produced {truth}%."
    if abs(float(reported) - float(truth)) > tolerance:
        return (
            False,
            0.0,
            f"Report states {reported}% for {primary_metric}; tool produced {truth}%.",
        )

    # Guardrail statuses must match the tool as well.
    tool_status = {
        g["metric"]: g["status"] for g in bundle.get("guardrail_status", {}).get("guardrails", [])
    }
    mismatched = [
        f"{i['metric']}: report {i['status']!r} vs tool {tool_status[i['metric']]!r}"
        for i in report.get("guardrail_status", {}).get("items", [])
        if i.get("metric") in tool_status and i.get("status") != tool_status[i["metric"]]
    ]
    if mismatched:
        return False, 0.0, "Guardrail status disagrees with the tool: " + "; ".join(mismatched)
    return True, 1.0, "Primary outcome figure and guardrail statuses match the tool output."


def required_segmentation(report, bundle, brief, expect, contract) -> Result:
    required = [str(s) for s in brief.get("required_segments", [])]
    checked = {_normalise_segment(s) for s in report.get("segments_checked", [])}
    missing = [s for s in required if _normalise_segment(s) not in checked]
    if missing:
        return (
            False,
            round(1 - len(missing) / max(len(required), 1), 2),
            f"segments_checked omits {', '.join(missing)}. A reader cannot tell whether "
            f"these were examined and found unremarkable.",
        )
    return True, 1.0, f"All {len(required)} contract-required segments recorded as checked."


def investigation_coverage(report, bundle, brief, expect, contract) -> Result:
    wanted = expect.get("must_identify_segments") or []
    found = {_normalise_segment(f.get("segment", "")) for f in report.get("segment_findings", [])}
    missing = [s for s in wanted if _normalise_segment(s) not in found]

    if missing:
        return (
            False,
            round(1 - len(missing) / max(len(wanted), 1), 2),
            f"The movement is concentrated in {', '.join(missing)}, which the report "
            f"does not identify as a segment finding.",
        )

    cap = expect.get("max_segment_findings")
    if cap is not None and len(report.get("segment_findings", [])) > cap:
        return (
            False,
            0.5,
            f"{len(report.get('segment_findings', []))} segment findings reported on a "
            f"case with nothing wrong (limit {cap}). Manufacturing findings in noise "
            f"trains readers to ignore the report.",
        )
    if not wanted:
        return True, 1.0, "Nothing to locate in this case, and no invented findings."
    return True, 1.0, f"Located {', '.join(wanted)}."


def instrumentation_awareness(report, bundle, brief, expect, contract) -> Result:
    instrumentation = report.get("instrumentation_health", {})
    status = instrumentation.get("status")
    allowed = expect.get("instrumentation_status") or []
    problems = []

    if allowed and status not in allowed:
        problems.append(f"instrumentation status {status!r} is not one of {allowed}")

    declared = {m for m in instrumentation.get("metrics_not_trustworthy") or []}
    for metric in expect.get("metrics_must_be_marked_untrustworthy") or []:
        if metric not in declared:
            problems.append(f"{metric} is compromised but not marked untrustworthy")

    if expect.get("must_flag_instrumentation") is False and status not in ("healthy",):
        problems.append(
            f"instrumentation is healthy in this case but reported as {status!r}"
        )

    if problems:
        return False, 0.0, "; ".join(problems)
    return True, 1.0, f"Instrumentation reported as {status!r}, consistent with the case."


def evidence_completeness(report, bundle, brief, expect, contract) -> Result:
    produced = set(bundle.get("evidence_ids") or [])
    indexed = {e.get("evidence_id") for e in report.get("evidence_index", [])}

    problems = []
    for index, fact in enumerate(report.get("facts", [])):
        if not fact.get("evidence_refs"):
            problems.append(f"facts[{index}] has no evidence reference")

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

    invented = sorted(cited - produced)
    if invented:
        problems.append(f"cites evidence no tool produced: {', '.join(invented[:4])}")
    unindexed = sorted(cited - indexed)
    if unindexed:
        problems.append(f"cited but not in evidence_index: {', '.join(unindexed[:4])}")

    if problems:
        return False, 0.0, "; ".join(problems)
    return True, 1.0, f"{len(cited)} citations, all produced by tools and indexed."


def causal_discipline(report, bundle, brief, expect, contract) -> Result:
    from reviewers import causal_language

    review = causal_language.review(report)
    blocking = [v for v in review["violations"] if v["severity"] == "blocking"]

    text = _report_text(report)
    forbidden = [p for p in expect.get("forbidden_phrases") or [] if p.lower() in text]

    # Explicit per-case check: the feature must not be blamed for these segments.
    attributed = []
    for segment in expect.get("must_not_attribute_to_feature") or []:
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", segment.lower()) if t]
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if not all(t in sentence for t in tokens):
                continue
            if re.search(r"\b(caused|because of|due to|drove|led to|resulted in|reduced|attributable to)\b", sentence) and (
                "feature" in sentence or "priority" in sentence or "introduction" in sentence
            ):
                attributed.append(f"{segment}: {sentence.strip()[:120]}")
                break

    problems = []
    if blocking:
        problems.append(
            "; ".join(f"{v['check']} at {v['location']}" for v in blocking[:4])
        )
    if forbidden:
        problems.append(f"forbidden phrasing present: {', '.join(forbidden)}")
    if attributed:
        problems.append("attributes movement to the feature where evidence cannot: " + "; ".join(attributed))

    if problems:
        return False, 0.0, " | ".join(problems)
    warnings = review["warning_count"]
    return (
        True,
        1.0 if not warnings else 0.85,
        f"No blocking causal violations ({warnings} warning(s)).",
    )


def escalation_behaviour(report, bundle, brief, expect, contract) -> Result:
    from coordinator import report_contract

    escalation = report_contract.evaluate_escalation(report, bundle, brief)
    expected_escalate = expect.get("must_escalate")
    reported = escalation["escalation_reported"]

    problems = []
    if expected_escalate is not None and reported != expected_escalate:
        problems.append(
            f"case requires escalate={expected_escalate}, report says {reported}"
        )
    if not escalation["agrees"]:
        problems.append(
            f"report and enabled rules disagree: {escalation['verdict']} "
            f"(rules fired: {[f['rule'] for f in escalation['fired']] or 'none'})"
        )

    required_rules = set(expect.get("escalation_must_include") or [])
    fired_rules = {f["rule"] for f in escalation["fired"]}
    dormant = {d["rule"] for d in escalation["would_have_fired_if_enabled"]}
    unenforced = sorted(required_rules - fired_rules)
    if unenforced:
        detail = f"expected rule(s) did not fire: {', '.join(unenforced)}"
        covered_but_off = sorted(set(unenforced) & dormant)
        if covered_but_off:
            detail += (
                f" — the check exists and would fire, but {', '.join(covered_but_off)} "
                f"is not enabled in src/schemas/escalation_rules.yaml"
            )
        problems.append(detail)

    if problems:
        return False, 0.0, " | ".join(problems)
    return (
        True,
        1.0,
        f"Escalation {'required' if reported else 'not required'} and rules agree "
        f"({', '.join(sorted(fired_rules)) or 'no rules fired'}).",
    )


def uncertainty_calibration(report, bundle, brief, expect, contract) -> Result:
    stated = (report.get("confidence_and_escalation", {}).get("overall_confidence") or "").lower()
    ceiling = (expect.get("max_overall_confidence") or "high").lower()
    if stated not in CONFIDENCE_ORDER:
        return False, 0.0, f"overall_confidence {stated!r} is not low/medium/high"
    if CONFIDENCE_ORDER[stated] > CONFIDENCE_ORDER[ceiling]:
        return (
            False,
            0.0,
            f"confidence {stated!r} exceeds {ceiling!r}, which is the most this "
            f"case's evidence supports",
        )

    hypotheses = [h for h in report.get("hypotheses", []) if not h.get("ruled_out")]
    levels = {(h.get("confidence") or "").lower() for h in hypotheses}
    if len(hypotheses) >= 3 and len(levels) == 1:
        return (
            False,
            0.5,
            f"all {len(hypotheses)} live hypotheses carry identical confidence "
            f"({levels.pop()!r}); the field is not discriminating between them",
        )
    return True, 1.0, f"Overall confidence {stated!r}, within what this case supports."


def alternative_explanations(report, bundle, brief, expect, contract) -> Result:
    text = _report_text(report)
    required = expect.get("must_name_context") or []
    missing = [ref for ref in required if ref.lower() not in text]
    if missing:
        return (
            False,
            round(1 - len(missing) / max(len(required), 1), 2),
            f"available in the evidence but never mentioned: {', '.join(missing)}",
        )

    live = [h for h in report.get("hypotheses", []) if not h.get("ruled_out")]
    if expect.get("must_identify_segments") and len(report.get("hypotheses", [])) < 2:
        return (
            False,
            0.5,
            "only one explanation considered for a case with a real movement; no "
            "alternative was engaged with or ruled out",
        )
    untested = [h for h in live if not (h.get("how_to_test") or "").strip()]
    if untested:
        return False, 0.5, f"{len(untested)} hypothesis/hypotheses with no way to test them"
    return True, 1.0, f"{len(report.get('hypotheses', []))} explanation(s) considered, each testable."


def recommendation_quality(report, bundle, brief, expect, contract) -> Result:
    actions = report.get("recommended_actions", [])
    escalate = report.get("confidence_and_escalation", {}).get("escalate")

    if not actions:
        return False, 0.0, "no recommended actions"
    unowned = [a for a in actions if not (a.get("owner") or "").strip()]
    if unowned:
        return False, 0.3, f"{len(unowned)} action(s) with no owner"
    if escalate and not any(a.get("blocks_product_decision") for a in actions):
        return (
            False,
            0.5,
            "the report escalates but no action is flagged as blocking a product "
            "decision, so nothing tells the reader to wait",
        )
    vague = [
        a
        for a in actions
        if (a.get("action") or "").strip().lower()
        in ("investigate further", "monitor", "keep monitoring", "continue monitoring")
    ]
    if vague:
        return False, 0.6, f"{len(vague)} action(s) that do not say what to do"
    return True, 1.0, f"{len(actions)} owned, specific action(s)."


SCORERS = {
    "metric_correctness": metric_correctness,
    "numerical_correctness": numerical_correctness,
    "required_segmentation": required_segmentation,
    "investigation_coverage": investigation_coverage,
    "instrumentation_awareness": instrumentation_awareness,
    "evidence_completeness": evidence_completeness,
    "causal_discipline": causal_discipline,
    "escalation_behaviour": escalation_behaviour,
    "uncertainty_calibration": uncertainty_calibration,
    "alternative_explanations": alternative_explanations,
    "recommendation_quality": recommendation_quality,
}


def score(dimension_id: str, report: dict, bundle: dict, brief: dict, expect: dict, contract: Any = None) -> Result:
    scorer = SCORERS.get(dimension_id)
    if scorer is None:
        return (
            True,
            0.0,
            f"no scorer implemented for {dimension_id!r} — dimension not evaluated",
        )
    return scorer(report, bundle, brief, expect, contract)
