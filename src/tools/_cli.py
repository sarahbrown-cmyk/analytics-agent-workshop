"""Shared plumbing for the deterministic tools.

Every tool in this directory:

1. takes the launch contract and a checkpoint, not free-form instructions
2. prints JSON to stdout and nothing else
3. stamps every block of results with an **evidence id**

The evidence id is the mechanism behind the whole workshop. It is derived from
what was asked, not from what came back, so it is stable across runs and can be
cited in a report. `src/coordinator/report_contract.py` then checks that every
citation in a report matches an evidence id that a tool actually produced — which
is how "every substantive claim carries an evidence reference" becomes something
enforced rather than something requested.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import _yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BRIEF = REPO_ROOT / "feature_briefs" / "priority-introductions.yaml"


def standard_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--brief",
        default=str(DEFAULT_BRIEF),
        help="Path to the launch contract YAML.",
    )
    parser.add_argument(
        "--checkpoint",
        type=int,
        default=30,
        help="Checkpoint in days since launch (30, 60, 90).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Metrics store directory. Defaults to synthetic_data/.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit single-line JSON instead of indented.",
    )
    return parser


def load_brief(path: str | Path) -> dict:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
    if not resolved.exists():
        fail(f"Launch contract not found: {resolved}")
    brief = _yaml.load_path(resolved)
    missing = [k for k in ("feature", "launch", "primary_outcome", "guardrail_metrics") if k not in brief]
    if missing:
        fail(f"Launch contract is missing required sections: {', '.join(missing)}")
    return brief


def emit(payload: dict[str, Any], compact: bool = False) -> None:
    if compact:
        sys.stdout.write(json.dumps(payload, default=str) + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")


def fail(message: str, code: int = 2) -> None:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(code)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def evidence_id(tool_code: str, *parts: Any) -> str:
    """A stable, readable, citable reference. Derived from the question asked."""
    slugs = []
    for part in parts:
        if part is None:
            continue
        slug = _SLUG_RE.sub("-", str(part).lower()).strip("-")
        if slug:
            slugs.append(slug)
    return "EV-" + tool_code.upper() + ("-" + "-".join(slugs) if slugs else "")


def envelope(tool: str, brief: dict, window, **extra: Any) -> dict[str, Any]:
    """The common header on every tool result."""
    payload = {
        "tool": tool,
        "feature_id": brief["feature"]["id"],
        "brief_version": brief["feature"].get("version"),
        "checkpoint_days": window.checkpoint_days,
        "window": window.as_dict(),
        "data_quality_warnings": list(window.notes),
    }
    payload.update(extra)
    return payload
