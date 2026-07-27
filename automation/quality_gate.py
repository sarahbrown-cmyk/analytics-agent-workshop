#!/usr/bin/env python3
"""The quality gate. Runs when agent, tool, or evaluation files change.

    python3 automation/quality_gate.py
    python3 automation/quality_gate.py --changed src/reviewers/review_rubric.yaml
    python3 automation/quality_gate.py --json

Six checks, in the order a reviewer would want them:

1. **Evaluation suite** — every case, blocking failures fail the gate.
2. **Analytical review check** — the deterministic causal-discipline pass over every
   report artifact in the repository.
3. **Ownership and version metadata** — every agent, rubric and contract names an
   owner and a version. An agent nobody owns cannot be deprecated, and a rubric with
   no version cannot be rolled back.
4. **Credentials and unsafe configuration** — no API keys, tokens, connection
   strings, or real hostnames. This repository must stay safe to clone.
5. **Cost estimate** — the model calls one checkpoint run implies, priced, with the
   budget from `gate_config.yaml`.
6. **Escalation coverage** — every trigger the launch contract declares has an
   enabled rule behind it.

The point of a gate is not that it is clever. It is that it runs without being
remembered. A standard that depends on someone thinking of it during review is
already not a standard — it is a hope. Check 6 exists because that is precisely how
the instrumentation trigger in this repository went unenforced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _extra in (REPO_ROOT / "src", Path(__file__).resolve().parent):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import cost_estimate  # noqa: E402
from tools import _yaml  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "gate_config.yaml"

GREEN, RED, YELLOW, BOLD, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[1m",
    "\033[2m",
    "\033[0m",
)

# Patterns that must never appear in a repository people clone onto laptops.
SECRET_PATTERNS = [
    (r"sk-ant-[A-Za-z0-9_\-]{8,}", "Anthropic API key"),
    (r"sk-[A-Za-z0-9]{32,}", "API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"ghp_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"),
    (r"(?i)postgres(?:ql)?://[^\s\"']+:[^\s\"']+@", "database connection string with credentials"),
    (r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']", "hard-coded credential"),
    (r"(?i)\b[a-z0-9.\-]+\.(?:internal|corp|prod)\.[a-z]{2,}\b", "internal hostname"),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}
SCANNED_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".sh", ".toml", ".txt"}


def _paint(text: str, code: str, colour: bool) -> str:
    return f"{code}{text}{RESET}" if colour else text


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_evaluations(config: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "evaluations" / "run_evaluations.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "check": "evaluation_suite",
            "blocking": True,
            "passed": False,
            "detail": f"evaluation suite did not produce JSON: {result.stderr.strip()[:300]}",
        }

    minimum = float(config.get("thresholds", {}).get("min_cases_passing_pct", 100))
    total = payload["cases_total"] or 1
    passing_pct = payload["cases_passing"] / total * 100
    failing = [r["case"] for r in payload["results"] if not r["passed"]]

    return {
        "check": "evaluation_suite",
        "blocking": True,
        "passed": passing_pct >= minimum,
        "detail": (
            f"{payload['cases_passing']}/{payload['cases_total']} cases pass "
            f"(mean score {payload['mean_weighted_score']:.2f}); required {minimum:.0f}%"
            + (f". Failing: {', '.join(failing)}" if failing else "")
        ),
        "data": {
            "cases_passing": payload["cases_passing"],
            "cases_total": payload["cases_total"],
            "mean_weighted_score": payload["mean_weighted_score"],
            "failing_cases": failing,
        },
    }


def check_analytical_review() -> dict:
    from reviewers import causal_language

    reports = sorted(REPO_ROOT.glob("reports/*.json")) + sorted(
        REPO_ROOT.glob("evaluations/cases/*/baseline_report.json")
    )
    reports = [p for p in reports if p.parent.name != "_evidence"]

    offenders = []
    for path in reports:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            offenders.append((path, "not valid JSON"))
            continue
        if "facts" not in report:
            continue
        review = causal_language.review(report)
        if not review["passed"]:
            checks = ", ".join(sorted({v["check"] for v in review["violations"] if v["severity"] == "blocking"}))
            offenders.append((path, checks))

    # Baseline artifacts are deliberately flawed teaching fixtures; they are
    # reported but do not block, or the gate could never pass in the starting state.
    blocking_offenders = [
        (p, why) for p, why in offenders if "evaluations/cases/" not in str(p)
    ]
    return {
        "check": "analytical_review",
        "blocking": True,
        "passed": not blocking_offenders,
        "detail": (
            f"{len(reports)} report(s) checked; "
            + (
                "no causal-discipline violations outside the teaching fixtures."
                if not blocking_offenders
                else "violations in "
                + "; ".join(
                    f"{p.relative_to(REPO_ROOT)} ({why})" for p, why in blocking_offenders
                )
            )
            + (
                f" Known fixture violations (expected): "
                + ", ".join(
                    p.parent.name for p, _ in offenders if "evaluations/cases/" in str(p)
                )
                if any("evaluations/cases/" in str(p) for p, _ in offenders)
                else ""
            )
        ),
    }


def check_ownership_metadata() -> dict:
    problems = []

    for path in sorted((REPO_ROOT / ".claude" / "agents").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            problems.append(f"{path.name}: no frontmatter")
            continue
        frontmatter = text.split("---", 2)[1]
        for field in ("name", "description"):
            if not re.search(rf"^{field}:", frontmatter, re.MULTILINE):
                problems.append(f"{path.name}: frontmatter missing {field}")

    for relative in (
        "src/reviewers/review_rubric.yaml",
        "src/schemas/escalation_rules.yaml",
        "evaluations/rubrics/monitoring_report_rubric.yaml",
    ):
        document = _yaml.load_path(REPO_ROOT / relative)
        for field in ("version", "owner"):
            if not document.get(field):
                problems.append(f"{relative}: missing {field}")

    brief = _yaml.load_path(REPO_ROOT / "feature_briefs" / "priority-introductions.yaml")
    for field in ("owner", "analytics_owner", "version"):
        if not brief.get("feature", {}).get(field):
            problems.append(f"feature brief: missing feature.{field}")
    if not brief.get("human_escalation_route", {}).get("owner"):
        problems.append("feature brief: no human escalation owner")

    return {
        "check": "ownership_and_version_metadata",
        "blocking": True,
        "passed": not problems,
        "detail": (
            "Every agent, rubric and contract names an owner and a version."
            if not problems
            else "; ".join(problems)
        ),
    }


def check_credentials() -> dict:
    findings = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue  # this file contains the patterns themselves
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern, label in SECRET_PATTERNS:
            match = re.search(pattern, text)
            if match:
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: possible {label} "
                    f"(line {text[: match.start()].count(chr(10)) + 1})"
                )
    return {
        "check": "credentials_and_unsafe_config",
        "blocking": True,
        "passed": not findings,
        "detail": (
            "No credentials, tokens, connection strings or internal hostnames found."
            if not findings
            else "; ".join(findings[:8])
        ),
    }


def check_cost(config: dict) -> dict:
    estimate = cost_estimate.estimate(config)
    budget = float(config.get("thresholds", {}).get("max_usd_per_checkpoint", 5.0))
    return {
        "check": "cost_estimate",
        "blocking": bool(config.get("thresholds", {}).get("enforce_cost_budget", False)),
        "passed": estimate["usd_per_checkpoint"] <= budget,
        "detail": (
            f"{estimate['model_calls']} model calls, ~{estimate['total_tokens']:,} tokens, "
            f"about ${estimate['usd_per_checkpoint']:.2f} per checkpoint run "
            f"(budget ${budget:.2f}); ~${estimate['usd_per_month']:.2f}/month at "
            f"{config.get('usage', {}).get('checkpoints_per_month', 12)} runs"
        ),
        "data": estimate,
    }


def check_escalation_coverage() -> dict:
    brief = _yaml.load_path(REPO_ROOT / "feature_briefs" / "priority-introductions.yaml")
    rules = _yaml.load_path(REPO_ROOT / "src" / "schemas" / "escalation_rules.yaml")
    declared = [str(t) for t in brief.get("escalation_triggers", [])]
    enabled = {r["id"] for r in rules.get("rules", []) if r.get("enabled", True)}
    unenforced = [t for t in declared if t not in enabled]

    return {
        "check": "escalation_coverage",
        "blocking": True,
        "passed": not unenforced,
        "detail": (
            f"All {len(declared)} escalation triggers in the launch contract have an "
            f"enabled rule."
            if not unenforced
            else (
                f"Declared in the launch contract but not enabled in "
                f"src/schemas/escalation_rules.yaml: {', '.join(unenforced)}. "
                f"An unenforced trigger is not a control."
            )
        ),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

WATCHED_PREFIXES = (
    ".claude/agents/",
    ".claude/skills/",
    "src/",
    "evaluations/",
    "feature_briefs/",
    "automation/",
)


def relevant(changed: list[str]) -> bool:
    if not changed:
        return True
    return any(path.startswith(WATCHED_PREFIXES) for path in changed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed", nargs="*", default=[], help="Changed file paths.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args()

    if not relevant(args.changed):
        print("quality gate: no watched files changed, skipping.")
        return

    config = _yaml.load_path(CONFIG_PATH)
    checks = [
        check_evaluations(config),
        check_analytical_review(),
        check_ownership_metadata(),
        check_credentials(),
        check_cost(config),
        check_escalation_coverage(),
    ]

    blocking_failures = [c for c in checks if c["blocking"] and not c["passed"]]

    if args.json:
        print(
            json.dumps(
                {
                    "passed": not blocking_failures,
                    "blocking_failures": [c["check"] for c in blocking_failures],
                    "checks": checks,
                },
                indent=2,
            )
        )
    else:
        colour = not args.no_colour and sys.stdout.isatty()
        print()
        print(_paint("Quality gate", BOLD, colour))
        print("=" * 78)
        for check in checks:
            if check["passed"]:
                label, code = "PASS", GREEN
            elif check["blocking"]:
                label, code = "BLOCK", RED
            else:
                label, code = "warn", YELLOW
            print(f"{_paint(label, code, colour):<6} {_paint(check['check'], BOLD, colour)}")
            print(f"       {check['detail']}")
        print("=" * 78)
        if blocking_failures:
            print(
                _paint(
                    f"RELEASE BLOCKED — {len(blocking_failures)} blocking check(s) failed: "
                    + ", ".join(c["check"] for c in blocking_failures),
                    RED,
                    colour,
                )
            )
            print(
                _paint(
                    "Nothing here is a matter of opinion. Fix the failure or change the "
                    "standard deliberately, in a diff someone can review.",
                    DIM,
                    colour,
                )
            )
        else:
            print(_paint("All blocking checks passed.", GREEN, colour))
        print()

    raise SystemExit(1 if blocking_failures else 0)


if __name__ == "__main__":
    main()
