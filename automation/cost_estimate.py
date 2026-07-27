#!/usr/bin/env python3
"""Estimate what one checkpoint run costs in model calls and tokens.

    python3 automation/cost_estimate.py

Cost belongs in the gate because a multi-agent design has a price, and the price is
invisible in a design diagram. Adding a sixth specialist looks free when you are
editing markdown. It is not: it is another call, another context window, on every run,
forever.

The arithmetic here is deliberately crude — a per-agent call count and a token
estimate from `gate_config.yaml`, not measured usage. The purpose is not accounting
accuracy. It is to make the cost of an architectural decision visible at the moment
the decision is made, and to let the team set a number they are willing to spend per
checkpoint and have it enforced.

Rates live in config so they can be corrected without touching code. Check them
against current published pricing before quoting these numbers to anyone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from tools import _yaml  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "gate_config.yaml"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def count_agents() -> int:
    return len(list(AGENTS_DIR.glob("*.md")))


def estimate(config: dict | None = None) -> dict:
    config = config or _yaml.load_path(CONFIG_PATH)
    cost = config.get("cost", {}) or {}
    usage = config.get("usage", {}) or {}

    agents = count_agents()
    calls_per_agent = float(cost.get("calls_per_agent_per_run", 2.5))
    coordinator_calls = float(cost.get("coordinator_calls_per_run", 4))
    input_tokens = float(cost.get("input_tokens_per_call", 18000))
    output_tokens = float(cost.get("output_tokens_per_call", 2200))
    input_rate = float(cost.get("usd_per_million_input_tokens", 3.0))
    output_rate = float(cost.get("usd_per_million_output_tokens", 15.0))
    checkpoints_per_month = float(usage.get("checkpoints_per_month", 12))

    # The coordinator plus one pass per specialist, times the retries a real run needs.
    specialists = max(agents - 1, 0)
    model_calls = coordinator_calls + specialists * calls_per_agent

    total_input = model_calls * input_tokens
    total_output = model_calls * output_tokens
    usd = (total_input / 1_000_000 * input_rate) + (total_output / 1_000_000 * output_rate)

    return {
        "agents_defined": agents,
        "specialists": specialists,
        "model_calls": round(model_calls, 1),
        "input_tokens": int(total_input),
        "output_tokens": int(total_output),
        "total_tokens": int(total_input + total_output),
        "usd_per_checkpoint": round(usd, 3),
        "usd_per_month": round(usd * checkpoints_per_month, 2),
        "checkpoints_per_month": checkpoints_per_month,
        "usd_per_additional_specialist": round(
            calls_per_agent
            * (
                input_tokens / 1_000_000 * input_rate
                + output_tokens / 1_000_000 * output_rate
            ),
            3,
        ),
        "note": (
            "Estimate from configured per-call assumptions, not measured usage. The "
            "figure worth attending to is usd_per_additional_specialist: that is what "
            "each new agent adds to every run from now on."
        ),
    }


def main() -> None:
    print(json.dumps(estimate(), indent=2))


if __name__ == "__main__":
    main()
