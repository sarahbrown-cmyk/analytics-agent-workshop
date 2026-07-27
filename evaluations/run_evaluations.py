#!/usr/bin/env python3
"""Run the evaluation suite and print a scorecard.

    python3 evaluations/run_evaluations.py
    python3 evaluations/run_evaluations.py --case 03
    python3 evaluations/run_evaluations.py --variant solution
    python3 evaluations/run_evaluations.py --report-dir reports --json

An evaluation here is a **versioned scenario with known correct behaviour**, not a
comparison against a reference paragraph. Each case ships its own data directory,
so the scenario is pinned: the same case scores the same way next month, and a
change in the scorecard means the system changed rather than the data drifting.

What gets scored is the report artifact for each case. Three variants:

    baseline   the starting state shipped with this repository (default)
    solution   the corrected reports in solutions/completed/reports/
    <dir>      your own reports, via --report-dir, named <case-id>.json

The suite calls no model and needs no API key. That is what makes it usable in a
pre-commit hook and identical for everyone in the room.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for extra in (REPO_ROOT / "src", REPO_ROOT / "evaluations"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from coordinator import run_checkpoint  # noqa: E402
from scorers import dimensions  # noqa: E402
from tools import _yaml  # noqa: E402

CASES_DIR = REPO_ROOT / "evaluations" / "cases"
RUBRIC_PATH = REPO_ROOT / "evaluations" / "rubrics" / "monitoring_report_rubric.yaml"
BRIEF_PATH = REPO_ROOT / "feature_briefs" / "priority-recommendations.yaml"
SOLUTION_REPORTS = REPO_ROOT / "solutions" / "completed" / "reports"

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)


def discover_cases(selector: str | None) -> list[Path]:
    cases = sorted(p for p in CASES_DIR.iterdir() if p.is_dir() and (p / "case.yaml").exists())
    if selector:
        cases = [c for c in cases if c.name.startswith(selector) or selector in c.name]
    return cases


def resolve_report_path(case_dir: Path, variant: str, report_dir: str | None) -> Path | None:
    if report_dir:
        candidate = Path(report_dir)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate / f"{case_dir.name}.json"
    if variant == "solution":
        return SOLUTION_REPORTS / f"{case_dir.name}.json"
    return case_dir / "baseline_report.json"


def run_case(case_dir: Path, rubric: dict, brief: dict, variant: str, report_dir: str | None) -> dict:
    case = _yaml.load_path(case_dir / "case.yaml")
    expect = case.get("expect", {}) or {}

    report_path = resolve_report_path(case_dir, variant, report_dir)
    if report_path is None or not report_path.exists():
        return {
            "case": case_dir.name,
            "name": case.get("name", case_dir.name),
            "status": "missing_report",
            "report_path": str(report_path),
            "dimensions": [],
            "passed": False,
            "weighted_score": 0.0,
        }

    report = json.loads(report_path.read_text(encoding="utf-8"))
    bundle = run_checkpoint.build(
        str(BRIEF_PATH), int(case.get("checkpoint", 30)), case.get("data_dir")
    )

    results = []
    for dimension in rubric.get("dimensions", []):
        passed, score, detail = dimensions.score(
            dimension["id"], report, bundle, brief, expect
        )
        results.append(
            {
                "dimension": dimension["id"],
                "blocking": bool(dimension.get("blocking")),
                "weight": float(dimension.get("weight", 1.0)),
                "passed": passed,
                "score": round(float(score), 3),
                "detail": detail,
            }
        )

    blocking_failures = [r for r in results if r["blocking"] and not r["passed"]]
    total_weight = sum(r["weight"] for r in results) or 1.0
    weighted = sum(r["weight"] * r["score"] for r in results) / total_weight

    return {
        "case": case_dir.name,
        "name": case.get("name", case_dir.name),
        "status": "scored",
        "report_path": str(report_path.relative_to(REPO_ROOT)),
        "dimensions": results,
        "blocking_failures": [r["dimension"] for r in blocking_failures],
        "passed": not blocking_failures,
        "weighted_score": round(weighted, 3),
    }


def print_scorecard(results: list[dict], variant: str, colour: bool) -> None:
    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if colour else text

    dimension_ids = [d["dimension"] for d in results[0]["dimensions"]] if results else []
    width = max((len(d) for d in dimension_ids), default=20)

    print()
    print(paint(f"Evaluation scorecard — variant: {variant}", BOLD))
    print("=" * 78)

    for result in results:
        if result["status"] == "missing_report":
            print(
                f"\n{paint('MISSING', YELLOW)}  {result['case']} — no report at "
                f"{result['report_path']}"
            )
            continue
        verdict = paint("PASS", GREEN) if result["passed"] else paint("FAIL", RED)
        print(
            f"\n{verdict}  {paint(result['case'], BOLD)} — {result['name']}  "
            f"{paint(f'score {result['weighted_score']:.2f}', DIM)}"
        )
        for dimension in result["dimensions"]:
            mark = "ok  " if dimension["passed"] else ("FAIL" if dimension["blocking"] else "warn")
            colour_code = GREEN if dimension["passed"] else (RED if dimension["blocking"] else YELLOW)
            print(
                f"    {paint(mark, colour_code)} {dimension['dimension']:<{width}}  "
                f"{dimension['detail']}"
            )

    scored = [r for r in results if r["status"] == "scored"]
    passing = [r for r in scored if r["passed"]]
    print()
    print("=" * 78)
    mean = sum(r["weighted_score"] for r in scored) / len(scored) if scored else 0.0
    summary = f"{len(passing)}/{len(scored)} cases pass   mean weighted score {mean:.2f}"
    print(paint(summary, BOLD if len(passing) == len(scored) else RED))

    failed = [r for r in scored if not r["passed"]]
    if failed:
        print()
        print("Blocking failures to look at, in order:")
        for result in failed:
            for dimension in result["dimensions"]:
                if dimension["blocking"] and not dimension["passed"]:
                    print(f"  {result['case']} / {dimension['dimension']}")
                    print(f"      {dimension['detail']}")
        print()
        print(
            "Read evaluations/expected_behaviors/ for what each case is testing, then\n"
            "change one thing and rerun. A rising mean score with a blocking failure\n"
            "still present is a regression, not progress."
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Run one case, e.g. 03 or instrumentation.")
    parser.add_argument(
        "--variant",
        default="baseline",
        choices=["baseline", "solution"],
        help="Which shipped report set to score.",
    )
    parser.add_argument(
        "--report-dir",
        help="Score your own reports from this directory, named <case-id>.json.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a scorecard.")
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args()

    rubric = _yaml.load_path(RUBRIC_PATH)
    brief = _yaml.load_path(BRIEF_PATH)
    cases = discover_cases(args.case)
    if not cases:
        sys.stderr.write("error: no matching evaluation cases\n")
        raise SystemExit(2)

    results = [run_case(c, rubric, brief, args.variant, args.report_dir) for c in cases]

    if args.json:
        scored = [r for r in results if r["status"] == "scored"]
        print(
            json.dumps(
                {
                    "variant": args.report_dir or args.variant,
                    "cases_total": len(scored),
                    "cases_passing": sum(1 for r in scored if r["passed"]),
                    "mean_weighted_score": round(
                        sum(r["weighted_score"] for r in scored) / len(scored), 3
                    )
                    if scored
                    else 0.0,
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        print_scorecard(results, args.variant, colour=not args.no_colour and sys.stdout.isatty())

    failed = [r for r in results if not r["passed"]]
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
