# Case 3 — Instrumentation failure

## What is in the data

`priority_intro_sent` stops firing reliably on Android/US from 2026-05-20, after
release `rel-1058` shipped an analytics SDK upgrade and event batching change to
exactly that segment. Completeness averages ~73% against a 95% floor, the event's
schema version bumps 4 → 5, and the null rate on a required property jumps.

Recorded adoption for Android/US roughly halves. **Users did not change.** The funnel
step after the broken event is unchanged, and observed volume ordering becomes
impossible — the later step now exceeds the earlier one, which cannot happen if the
earlier event were being recorded correctly.

Deliberately placed on a different event, platform and market from the workshop's
own scenario, so nobody passes by remembering "Android GB payments".

## Correct behaviour

- Report instrumentation as `below_floor` and name `feature_adoption_rate` as not
  trustworthy in that cell.
- Describe the movement as **recorded** adoption falling, never as users sending
  fewer introductions.
- Cite the impossible-ordering finding. It is the strongest evidence available.
- Name `rel-1058` as the temporally and dimensionally matching release, without
  asserting it as proven cause.
- Escalate on instrumentation.
- Rule the behaviour-change hypothesis **out**, explicitly, with the reason.

## Why this case fails in the starting state

The report shipped as the baseline for this case is analytically correct. It fails
anyway, on `escalation_behaviour`, with `over_escalated`.

The launch contract lists six escalation triggers. `src/schemas/escalation_rules.yaml`
implements five. `instrumentation_below_floor` — the one this case needs — is
missing, so the system computes "no escalation required" while the report says
escalate, and the two disagree.

The check itself already exists in `report_contract.py`. It is simply not switched
on. Enabling it is four lines of YAML.

This is the lesson the case is really carrying: **a correct analysis can still fail a
badly configured gate, and an unenforced standard is not a standard.** The gap was
invisible until an evaluation made it visible.

## What the scorers do not check

Whether the remediation is the right one. "Backfill from server-side records" might
be impossible in a real system for reasons no scorer here knows about.
