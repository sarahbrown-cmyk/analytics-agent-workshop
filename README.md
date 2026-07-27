# Building Trustworthy Analytical Agents

A two-hour, code-centred Claude Code workshop for an analytics organisation.

> **Build, test, and operationalise an analytical agent that can be trusted — not
> just an impressive analysis that works once.**

Everything here is fabricated. No real company data, metric definition, credential,
brand, or system is represented. Nothing connects to a production service.

## What you will build

A post-launch monitoring agent for a fictional consumer-app feature called **Priority
Recommendations**. At its day-30 checkpoint the agent must read a launch contract,
retrieve verified numbers, investigate what moved, challenge its own conclusions,
produce an evidence-backed report, and escalate to a human when the evidence does not
support a conclusion.

The scenario is built so the honest answer is uncomfortable. Adoption looks healthy.
The primary outcome is up. And something is badly wrong in a place the aggregate
cannot see — but it is **not** the feature, and a confident agent will say it is.

```
Build → Review → Evaluate → Enforce → Operate
```

## Setup

Python 3.11 or newer. That is the entire dependency list.

```bash
git clone <repository-url>
cd analytics-agent-workshop
python3 --version          # 3.11+
python3 evaluations/run_evaluations.py
```

You should see **3 of 5 evaluation cases passing**. That is the correct starting
state: two cases fail on purpose, and finding out why is the workshop.

No virtualenv, no `pip install`, no API key needed for the tools or the evaluations.
Claude Code itself needs your normal sign-in.

## Layout

```
feature_briefs/           the launch contract — what success means, before any data
synthetic_data/           the local metrics store (CSV + JSON), and its generator
src/tools/                deterministic analysis. SQL over an in-memory store
src/coordinator/          holds the contract, assembles the report, enforces it
src/specialists/          bounded analyst definitions and handoff validation
src/reviewers/            the review rubric and the causal-language detector
src/schemas/              report contract, handoff contract, escalation rules
evaluations/              five versioned scenarios, scorers, and the scorecard
automation/               the quality gate and the hook that runs it
.claude/agents/           the coordinator, four specialists, and the reviewer
.claude/skills/           the reusable analytical-review skill
solutions/                checkpoints, and corrected artifacts for recovery
```

## The commands you will actually use

```bash
# What does the contract say success is?
cat feature_briefs/priority-recommendations.yaml

# Verified numbers. The model never computes these.
python3 src/tools/metric_movement.py --checkpoint 30
python3 src/tools/segment_breakdown.py --metric subscription_conversion_rate --by platform,market
python3 src/tools/funnel_analysis.py --platform Android --market GB
python3 src/tools/instrumentation_check.py --event payment_completed
python3 src/tools/launch_context.py --focus-platform Android --focus-market GB
python3 src/tools/guardrail_check.py --checkpoint 30

# Everything at once, as one evidence bundle
python3 src/coordinator/run_checkpoint.py --out reports/_evidence/priority-recommendations-day30.json

# Is a report allowed to be published?
python3 src/coordinator/report_contract.py reports/priority-recommendations-day30.json \
    --evidence reports/_evidence/priority-recommendations-day30.json

# Does the system still behave?
python3 evaluations/run_evaluations.py
python3 automation/quality_gate.py
```

## The one idea

The model should not recompute in prose what deterministic code can calculate. It
should interpret verified results.

Every design decision here follows from that. Date windows, metric deltas, threshold
checks, and escalation rules are code, because they have one correct answer and it
should not vary with the weather. Hypothesis generation, choosing the next diagnostic
step, weighing competing explanations, and writing the narrative are model work,
because judgment is the thing a model is actually for.

The interesting part is the boundary, and most of this repository is an argument about
where to draw it.

## Where to start

- **New to Claude Code?** `participant-guide.md`, then
  `prompts/beginner-copyable-prompts.md`. Every prompt is copy-paste ready.
- **Comfortable in a repo?** `prompts/advanced-challenges.md`.
- **Running the session?** `facilitator-guide.md`, including what to do when a live
  demo misbehaves.
