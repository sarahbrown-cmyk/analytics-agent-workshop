#!/usr/bin/env python3
"""Claude Code PostToolUse hook. Runs the quality gate after a relevant edit.

Wired up in `.claude/settings.json`. Claude Code passes the tool call as JSON on
stdin; this script pulls out the edited path, decides whether it is one of the
watched paths in `automation/gate_config.yaml`, and runs the gate if so.

Why a hook rather than a documented step: a standard that depends on someone
remembering to run it is not a standard. The team agreed the evaluation suite must
pass before an agent change ships. This is that agreement, executable.

The hook reports and does not block the edit. Blocking a keystroke-level edit would
make the repository unusable — you would be unable to save a half-finished change.
The gate blocks the *release*, in CI or at review; the hook makes sure you find out
within a second or two rather than at the end of the afternoon.

The whole gate takes about a second, which is the only reason running it on every
edit is reasonable. If it grows past a few seconds, split it: fast checks here, the
full suite at commit.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from tools import _yaml  # noqa: E402

CONFIG = _yaml.load_path(Path(__file__).resolve().parent / "gate_config.yaml")
WATCHED = tuple(str(p) for p in CONFIG.get("watched_paths", []))


def edited_paths(payload: dict) -> list[str]:
    tool_input = payload.get("tool_input") or {}
    candidates = [
        tool_input.get("file_path"),
        tool_input.get("path"),
        tool_input.get("notebook_path"),
    ]
    paths = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            paths.append(str(Path(candidate).resolve().relative_to(REPO_ROOT)))
        except ValueError:
            continue  # edit outside this repository
    return paths


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return

    paths = edited_paths(payload)
    watched = [p for p in paths if p.startswith(WATCHED)]
    if not watched:
        return

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "automation" / "quality_gate.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"quality gate could not run: {result.stderr.strip()[:300]}")
        return

    changed = ", ".join(watched)
    if report["passed"]:
        print(f"quality gate: all blocking checks pass ({changed}).")
        return

    print(f"quality gate BLOCKED after editing {changed}:")
    for check in report["checks"]:
        if check["blocking"] and not check["passed"]:
            print(f"  - {check['check']}: {check['detail']}")
    print("  run: python3 automation/quality_gate.py")


if __name__ == "__main__":
    main()
