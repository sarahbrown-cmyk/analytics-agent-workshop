---
name: analytical-review
description: Challenge an analytical conclusion before anyone acts on it. Use when reviewing a monitoring report, an investigation write-up, a metric read-out, or any document that explains why a number moved. Checks metric definitions, evidence, causal discipline, alternative explanations, confidence calibration, and whether recommendations exceed the evidence.
---

# Analytical review

A reusable review pass for any document that claims to explain a metric. The
monitoring report in this repository is one such document; a Looker read-out, an
experiment write-up, or a Slack thread that concluded something are others.

## When this applies

Any time a document moves from *what happened* to *why it happened*, or from *why*
to *what we should do*. Those two transitions are where analytical work goes wrong,
and they are almost never marked in the text.

## The seven questions

Work through these in order. Stop and record a blocking objection as soon as one
fails — do not batch them at the end, because a failure early on usually changes
what the later questions mean.

### 1. Is every metric what the document thinks it is?

Check each metric against its governed definition. Watch for a mean described as a
percentage, a proxy reported as the underlying thing, a rate whose denominator
changed between the periods being compared, and any metric with no definition at
all.

### 2. Could this be measurement rather than behaviour?

For every movement, ask which events the metric is derived from and whether those
events were healthy in the affected cell. A drop in a recorded event and a drop in
what users did are different claims. Compare against the adjacent downstream event:
if it held steady, the movement is recording, not behaviour.

### 3. Does the claimed cause reach the affected users?

An explanation must be able to touch the segment where the movement is. A feature
in treatment cannot move control. A release that shipped to one market cannot
explain a movement in another. Check the intersection before accepting the story.

### 4. Was every required segment examined?

Not "were interesting segments reported" — was every segment that should have been
checked, checked? A document that reports only where it found something cannot be
distinguished from one where nobody looked.

### 5. What else was happening?

List the alternative explanations available in the evidence: overlapping
experiments, releases, seasonality, mix shift, pricing, a processor change. For each,
say what would confirm or rule it out. A document with one explanation and no
rejected alternatives has not investigated; it has narrated.

### 6. Does confidence track the evidence?

Confidence should fall when the sample is small, the window incomplete, the
instrumentation degraded, or two explanations equally supported. Uniform confidence
across every claim means the field is decorative.

### 7. Does the recommendation stay inside the evidence?

Ask what a reader would do after reading this, and whether the evidence supports
that action. Recommending a rollback on evidence that cannot separate a measurement
failure from a behaviour change is the expensive version of this error.

## Deterministic support

Some of this is mechanical and should not depend on anyone remembering:

```bash
python3 src/reviewers/causal_language.py <report>.json
python3 src/coordinator/report_contract.py <report>.json --evidence <bundle>.json
```

`causal_language.py` finds causal wording in sections reserved for observations,
certainty that exceeds a stated confidence level, and — most usefully — a claim
crediting the feature for a movement the document itself recorded as symmetric
across arms.

Run these first. They are free, they never get tired, and they clear the mechanical
failures so the review can spend its attention on judgment.

## Output

For each objection: check, location, the text at fault, why the evidence does not
support it, and the smallest change that would fix it. Close with `PASS` or `BLOCK`,
and list any failure mode you had to reason about because no check covered it —
that gap is worth more than the objection.

## The standard

Pass a document when a competent reader who disagrees with its conclusion could
still follow every claim to its evidence and see why the author concluded what they
did. Block it when the document would survive that reader only because they trusted
the author.
