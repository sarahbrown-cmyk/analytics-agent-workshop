# Specialists

Four bounded analysts, defined in `../../.claude/agents/`, plus the code that keeps
them honest.

```
monitoring-coordinator
├── outcome-guardrail-analyst        primary outcome + guardrails
├── segment-funnel-analyst           where the movement is concentrated
├── instrumentation-health-analyst   can we trust the measurement
├── launch-context-analyst           what else was happening
└── analytical-reviewer              challenges the assembled draft
```

## When splitting work into specialists is worth it

- The responsibilities are genuinely different kinds of analysis, not the same
  analysis on different data.
- Each has a bounded input and a bounded output.
- Several hypotheses need investigating without one contaminating the others — the
  instrumentation analyst is more useful precisely because it does not know which
  segment the segment analyst found interesting.
- The specialist is reusable across workflows. `analytical-review` reviews any
  metric explanation, not just this report.

## When it is not

- **A deterministic function would do it.** Applying a date window, computing a
  delta, checking a threshold. Four of the five specialists here mostly call tools;
  they exist for the interpretation around the tool call, not the calculation.
- **To look sophisticated.** A five-agent tree that produces the same report as one
  agent is a more expensive, slower, harder-to-debug way to be equally right.
- **Overlapping responsibilities.** Two specialists analysing segments will
  disagree at the margins, and the coordinator will resolve it by picking one.
  `handoff.py --> detect_overlap` exists to catch this.
- **The cost exceeds the decision value.** Five specialist calls plus a review pass
  on a checkpoint nobody reads is waste, however elegant.
- **There is no structured handoff.** Without a fixed return shape, the coordinator
  paraphrases prose and the evidence trail breaks at the first summary.

## The handoff

Every specialist returns the same five things — finding, evidence reference,
confidence, limitations, recommended next step — enforced by
`specialist_finding.schema.json` via `handoff.py`.

Uniformity is what makes them composable. The coordinator can combine the
instrumentation analyst's output with the segment analyst's without knowing how
either works, and any specialist can be replaced without touching the others.

`handoff.py` also rejects two specific things: root-cause language in a specialist
finding (observations are theirs, causes are the coordinator's, and only after
review), and `limitations: "none"`, which is almost never true and is usually a sign
the specialist did not think about what it could not see.
