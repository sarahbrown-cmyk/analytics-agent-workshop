#!/usr/bin/env python3
"""Validate specialist handoffs, and detect specialists doing each other's jobs.

Subagents earn their cost when each one has a bounded responsibility and returns a
predictable shape. Two failure modes destroy that, and both are invisible without
a check:

**Unstructured handoff.** A specialist returns prose, the coordinator paraphrases
it, and the evidence reference is lost in translation. `validate_handoff` rejects
anything that does not carry finding, evidence, confidence, limitations and a next
step.

**Overlapping scope.** Two specialists both analyse segments, disagree slightly,
and the coordinator silently picks one. `detect_overlap` flags findings that cite
the same evidence from different specialists — the signal that a responsibility
boundary has blurred and you are now paying twice for one answer.

Usage:
    python3 src/specialists/handoff.py handoffs/*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from schemas import _validate  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "src" / "schemas" / "specialist_finding.schema.json"

# A specialist whose findings are this fraction shared with another specialist is
# not a specialist.
OVERLAP_THRESHOLD = 0.5


def validate_handoff(handoff: dict) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = _validate.validate(handoff, schema)

    # Root-cause language is the coordinator's to write, and only after review.
    # A specialist that explains rather than observes has exceeded its brief.
    for index, finding in enumerate(handoff.get("findings", [])):
        text = (finding.get("finding") or "").lower()
        for phrase in ("root cause", "caused by", "because of", "due to"):
            if phrase in text:
                errors.append(
                    f"$.findings[{index}]: contains {phrase!r}. A specialist reports "
                    f"observations; assembling them into a cause is the coordinator's "
                    f"job, after the reviewer has passed it."
                )
                break

    if (handoff.get("limitations") or "").strip().lower() in ("", "none", "n/a", "no limitations"):
        errors.append(
            "$.limitations: 'none' is almost never honest. State what this "
            "specialist could not establish."
        )
    return errors


def detect_overlap(handoffs: list[dict]) -> list[dict]:
    by_specialist: dict[str, set[str]] = {}
    for handoff in handoffs:
        name = handoff.get("specialist", "unknown")
        refs = {
            ref
            for finding in handoff.get("findings", [])
            for ref in finding.get("evidence_refs", [])
        }
        by_specialist.setdefault(name, set()).update(refs)

    overlaps = []
    names = sorted(by_specialist)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            shared = by_specialist[left] & by_specialist[right]
            if not shared:
                continue
            smaller = min(len(by_specialist[left]), len(by_specialist[right])) or 1
            share = len(shared) / smaller
            if share >= OVERLAP_THRESHOLD:
                overlaps.append(
                    {
                        "specialists": [left, right],
                        "shared_evidence": sorted(shared)[:8],
                        "overlap_share": round(share, 2),
                        "why": (
                            f"{left} and {right} draw {share:.0%} of their findings from "
                            f"the same evidence. Either merge them or sharpen the "
                            f"boundary — you are currently paying for two calls to "
                            f"answer one question."
                        ),
                    }
                )
    return overlaps


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.stderr.write("usage: handoff.py <handoff.json> [...]\n")
        raise SystemExit(2)

    handoffs = []
    all_errors: dict[str, list[str]] = {}
    for path in paths:
        if not path.exists():
            all_errors[str(path)] = ["file not found"]
            continue
        handoff = json.loads(path.read_text(encoding="utf-8"))
        handoffs.append(handoff)
        errors = validate_handoff(handoff)
        if errors:
            all_errors[str(path)] = errors

    result = {
        "handoffs_checked": len(handoffs),
        "errors": all_errors,
        "scope_overlap": detect_overlap(handoffs),
        "passed": not all_errors,
    }
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
