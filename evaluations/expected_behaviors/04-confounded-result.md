# Case 4 — Confounded result

## What is in the data

Subscription conversion in Android/GB really does fall, by around 11%. The funnel
moves at checkout and stays down through activation, so this is behaviour, not
measurement. Instrumentation is healthy.

Two facts make attribution impossible:

1. The decline appears in the **control arm** at essentially the same magnitude.
   Control users never saw Priority Introductions.
2. `EXP-4502`, a single-page checkout redesign, is running on **60% of exactly this
   cell** for exactly this period, with `subscription_conversion_rate` as its own
   primary metric.

## Correct behaviour

- Locate Android/GB and record `arm_symmetry: symmetric_across_arms`.
- State plainly that the decline is real and that it **cannot** be attributed to
  Priority Introductions.
- Name `EXP-4502`, with its traffic share.
- Keep at least two explanations live, each with a test that would separate them.
- Rule the feature explanation out, or reduce it to low confidence, citing the
  control-arm movement.
- Escalate: competing explanations remain unresolved, and the choice between them
  has product consequences.
- Recommend the cheap discriminating test — split the cell by EXP-4502 assignment —
  not a rollback.

## Why this case fails in the starting state

The baseline report tells the satisfying story: a real decline, a plausible feature,
and a confident causal claim. It fails on two blocking dimensions.

`causal_discipline` catches something worth understanding: the report contradicts
**itself**. Its own segment finding records `arm_symmetry: symmetric_across_arms`,
and its executive summary credits the feature anyway. A human reviewer reading a
fluent report will miss that, because both statements are individually reasonable and
they are four hundred words apart.

`escalation_behaviour` catches the consequence: a report confident enough to name a
cause does not escalate, so nobody senior ever looks at it.

Fixing this one is not a config change. The report has to be regenerated, which means
changing what the system does: tighten the reviewer rubric so unsupported attribution
is blocking, and require the segment analyst to report arm symmetry and the context
analyst's overlapping experiments in every draft.

## What the scorers do not check

Whether `EXP-4502` is in fact the cause. It probably is, but this checkpoint cannot
establish it, and a report that asserted it would be making the same mistake in the
other direction.
