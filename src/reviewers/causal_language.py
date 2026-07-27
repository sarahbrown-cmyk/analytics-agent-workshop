#!/usr/bin/env python3
"""Detect causal claims and false certainty in a report.

Language is where analytical discipline actually leaks. "Android conversion fell
33% in GB" and "Priority Recommendations reduced Android conversion in GB by 33%"
can be produced from the same tool output, cite the same evidence id, and pass
every schema check — but only one of them is supportable, and the other one gets
a feature rolled back.

This module is deliberately deterministic and deliberately dumb. It does not
judge whether a causal claim is *correct*; it finds causal claims where the report
structure says there should not be any:

- a `facts` entry using causal language, when facts are supposed to be observations
- a hypothesis asserted with certainty words while its own confidence is not high
- a causal claim about the monitored feature in a cell whose movement is symmetric
  across arms, which the arm-symmetry check has already ruled out
- an executive summary asserting a cause with no hypothesis backing it

A model reviewer can be argued out of an objection. A regular expression cannot,
which is the point of putting this layer underneath the model reviewer rather
than trusting the reviewer alone.

Usage:
    python3 src/reviewers/causal_language.py reports/priority-recommendations-day30.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CAUSAL_PATTERNS = [
    r"\bcaused\b",
    r"\bcausing\b",
    r"\bcause of\b",
    r"\bbecause of\b",
    r"\bdue to\b",
    r"\bdrove\b",
    r"\bdriven by\b",
    r"\bled to\b",
    r"\bresulted in\b",
    r"\bresulting in\b",
    r"\bas a result of\b",
    r"\bresponsible for\b",
    r"\battributable to\b",
    r"\bexplains\b",
    r"\bthis is why\b",
    r"\bimpact of\b",
]

CERTAINTY_PATTERNS = [
    r"\bclearly\b",
    r"\bobviously\b",
    r"\bdefinitely\b",
    r"\bcertainly\b",
    r"\bproves\b",
    r"\bproven\b",
    r"\bconfirms\b",
    r"\bconfirmed that\b",
    r"\bwithout doubt\b",
    r"\bconclusively\b",
    r"\bmust be\b",
]

HEDGE_PATTERNS = [
    r"\bmay\b",
    r"\bmight\b",
    r"\bcould\b",
    r"\bconsistent with\b",
    r"\bsuggests\b",
    r"\bpossible\b",
    r"\bhypothesis\b",
    r"\bwould need\b",
    r"\bcannot be ruled out\b",
]

_CAUSAL_RE = re.compile("|".join(CAUSAL_PATTERNS), re.IGNORECASE)
_CERTAINTY_RE = re.compile("|".join(CERTAINTY_PATTERNS), re.IGNORECASE)
_HEDGE_RE = re.compile("|".join(HEDGE_PATTERNS), re.IGNORECASE)


def matches(pattern: re.Pattern, text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in pattern.finditer(text or "")})


def review(report: dict) -> dict:
    violations: list[dict] = []

    for index, fact in enumerate(report.get("facts", [])):
        statement = fact.get("statement", "")
        found = matches(_CAUSAL_RE, statement)
        if found:
            violations.append(
                {
                    "check": "causal_language_in_facts",
                    "severity": "blocking",
                    "location": f"facts[{index}]",
                    "terms": found,
                    "statement": statement,
                    "why": (
                        "Facts are observations. Causal wording here presents an "
                        "explanation as though it were measured. Move the claim to "
                        "hypotheses, with what would test it."
                    ),
                }
            )
        certainty = matches(_CERTAINTY_RE, statement)
        if certainty:
            violations.append(
                {
                    "check": "false_certainty_in_facts",
                    "severity": "warning",
                    "location": f"facts[{index}]",
                    "terms": certainty,
                    "statement": statement,
                    "why": "A fact does not need to insist on itself. Drop the intensifier.",
                }
            )

    for index, hypothesis in enumerate(report.get("hypotheses", [])):
        statement = hypothesis.get("statement", "")
        confidence = (hypothesis.get("confidence") or "").lower()
        certainty = matches(_CERTAINTY_RE, statement)
        if certainty and confidence != "high":
            violations.append(
                {
                    "check": "certainty_exceeds_confidence",
                    "severity": "blocking",
                    "location": f"hypotheses[{index}]",
                    "terms": certainty,
                    "statement": statement,
                    "why": (
                        f"Stated with certainty while carrying {confidence or 'no'} "
                        f"confidence. The wording and the confidence field must agree."
                    ),
                }
            )
        if not hypothesis.get("ruled_out") and not matches(_HEDGE_RE, statement) and matches(_CAUSAL_RE, statement):
            violations.append(
                {
                    "check": "unhedged_causal_hypothesis",
                    "severity": "warning",
                    "location": f"hypotheses[{index}]",
                    "terms": matches(_CAUSAL_RE, statement),
                    "statement": statement,
                    "why": (
                        "A hypothesis phrased as a settled cause reads as a finding "
                        "once it leaves this document. Phrase it as a candidate."
                    ),
                }
            )

    summary = report.get("executive_summary", "") or ""
    if matches(_CAUSAL_RE, summary) and not matches(_HEDGE_RE, summary):
        violations.append(
            {
                "check": "unhedged_causal_summary",
                "severity": "blocking",
                "location": "executive_summary",
                "terms": matches(_CAUSAL_RE, summary),
                "statement": summary[:240],
                "why": (
                    "The executive summary is the only part most readers will see. An "
                    "unhedged causal claim here becomes the organisation's belief."
                ),
            }
        )

    violations.extend(_feature_blamed_on_symmetric_movement(report))

    blocking = [v for v in violations if v["severity"] == "blocking"]
    return {
        "check": "causal_discipline",
        "violations": violations,
        "blocking_count": len(blocking),
        "warning_count": len(violations) - len(blocking),
        "passed": not blocking,
    }


def _feature_blamed_on_symmetric_movement(report: dict) -> list[dict]:
    """The specific error this repository is built around.

    If a segment finding records that a movement appeared in the control arm too,
    then no claim anywhere in the report may attribute that movement to the
    feature. Control users never saw it.
    """
    symmetric_segments = [
        finding.get("segment", "")
        for finding in report.get("segment_findings", [])
        if finding.get("arm_symmetry") in ("symmetric_across_arms", "control_only")
    ]
    if not symmetric_segments:
        return []

    feature_id = (report.get("feature_id") or "").replace("-", " ")
    feature_terms = [t for t in feature_id.split() if len(t) > 3] + ["the feature"]

    violations = []
    haystacks = [("executive_summary", report.get("executive_summary", ""))]
    haystacks += [
        (f"hypotheses[{i}]", h.get("statement", ""))
        for i, h in enumerate(report.get("hypotheses", []))
        if not h.get("ruled_out")
    ]
    haystacks += [
        (f"facts[{i}]", f.get("statement", "")) for i, f in enumerate(report.get("facts", []))
    ]

    for location, text in haystacks:
        lowered = (text or "").lower()
        if not _CAUSAL_RE.search(lowered):
            continue
        if not any(term.lower() in lowered for term in feature_terms):
            continue
        for segment in symmetric_segments:
            tokens = [t.lower() for t in re.split(r"[^A-Za-z0-9]+", segment) if len(t) > 1]
            if tokens and all(t in lowered for t in tokens):
                violations.append(
                    {
                        "check": "feature_blamed_for_symmetric_movement",
                        "severity": "blocking",
                        "location": location,
                        "terms": [segment],
                        "statement": (text or "")[:240],
                        "why": (
                            f"The report itself records that the movement in {segment} "
                            f"appeared in the control arm. A feature shipped only to "
                            f"treatment cannot have caused it. This claim contradicts "
                            f"the report's own evidence."
                        ),
                    }
                )
                break
    return violations


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: causal_language.py <report.json>\n")
        raise SystemExit(2)
    path = Path(sys.argv[1])
    if not path.exists():
        sys.stderr.write(f"error: report not found: {path}\n")
        raise SystemExit(2)
    result = review(json.loads(path.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
