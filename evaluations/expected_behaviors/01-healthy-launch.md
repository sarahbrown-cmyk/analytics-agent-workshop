# Case 1 — Healthy launch

## What is in the data

Nothing is wrong. The primary outcome sits inside the contract's expected band, all
three guardrails are within threshold at aggregate and segment level, every critical
event is above the completeness floor, and no required segment is missing.

## Correct behaviour

- Report the primary outcome as `within_expected_range`.
- Report all three guardrails as passing, with evidence.
- **Do not escalate.** No enabled escalation rule fires.
- **Do not manufacture a finding.** At most one or two segment findings, and only if
  something genuinely stands out. Zero is the expected answer.
- Confidence may be `high`. This is the one case where it is earned.

## The failure mode being tested

Inventing a concern. An agent that is rewarded — implicitly, by the shape of its
instructions — for surfacing something will always find something, because in eight
platform-market cells some cell has always moved a few percent.

A monitoring system that raises a concern every month is worse than no monitoring
system, because it consumes the attention that a real problem will need later. The
`max_segment_findings: 2` expectation in `case.yaml` exists to enforce restraint.

## What the scorers do not check

Whether the executive summary is *useful*. A report can pass this case while being
too vague to be worth reading. Judge that yourself.
